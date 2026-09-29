import type {
  NexusBridgeStatus,
  NexusDecision,
  NexusDecisionRequest,
  NexusEvidenceInput,
} from '../core/nexus';
import {
  NexusMissionExecutor,
  type MissionEvidenceBundle,
  type MissionEvidenceProvider,
  type MissionEvidenceProviderStatus,
  type NexusDecisionEngine,
  UnavailableMissionEvidenceProvider,
} from '../mobile/nexus-mission-executor';
import type { MissionExecutionInput } from '../mobile/mission-control';

class FakeEngine implements NexusDecisionEngine {
  readonly requests: NexusDecisionRequest[] = [];
  constructor(
    private readonly ready: boolean,
    private readonly decision: NexusDecision,
  ) {}

  async getStatus(): Promise<NexusBridgeStatus> {
    return {
      configured: this.ready,
      ready: this.ready,
      corePath: this.ready ? '/fixture/nexus' : null,
      error: this.ready ? null : 'not ready',
    };
  }

  async evaluate(request: NexusDecisionRequest): Promise<NexusDecision> {
    this.requests.push(request);
    return this.decision;
  }
}

class FakeEvidenceProvider implements MissionEvidenceProvider {
  constructor(
    private readonly status: MissionEvidenceProviderStatus,
    private readonly bundle: MissionEvidenceBundle,
  ) {}

  async getStatus(): Promise<MissionEvidenceProviderStatus> {
    return this.status;
  }

  async collect(input: MissionExecutionInput): Promise<MissionEvidenceBundle> {
    void input;
    return this.bundle;
  }
}

function evidence(): NexusEvidenceInput[] {
  return [{
    id: 'e1',
    claim: 'Verified fixture claim',
    stance: 'support',
    sourceId: 'fixture-source',
    sourceFamily: 'fixture',
    trustBoundary: 'fixture-boundary',
    verified: true,
    citation: 'fixture://e1',
    contentHash: 'sha256:fixture',
  }];
}

function allPassDecision(overrides: Partial<NexusDecision> = {}): NexusDecision {
  return {
    decision: 'YES',
    approved: true,
    pipelinePasses: {
      grand_council: true,
      neis: true,
      blinded_dissent: true,
      verifier: true,
    },
    reasons: ['All canonical gates passed.'],
    evidenceIds: ['e1'],
    ...overrides,
  };
}

describe('NexusMissionExecutor', (): void => {
  test('is available only when NEXUS and the evidence provider are both ready', async (): Promise<void> => {
    const engine = new FakeEngine(true, allPassDecision());
    const readyProvider = new FakeEvidenceProvider({
      interactiveMissionsAvailable: true,
      researchMissionsAvailable: false,
      configuredProviders: ['fixture-provider'],
    }, { evidence: evidence() });

    const executor = new NexusMissionExecutor(engine, readyProvider);
    await expect(executor.getStatus()).resolves.toEqual({
      interactiveMissionsAvailable: true,
      researchMissionsAvailable: false,
      configuredProviders: ['fixture-provider'],
    });

    const blocked = new NexusMissionExecutor(
      new FakeEngine(false, allPassDecision()),
      readyProvider,
    );
    await expect(blocked.getStatus()).resolves.toEqual({
      interactiveMissionsAvailable: false,
      researchMissionsAvailable: false,
      configuredProviders: ['fixture-provider'],
    });
  });

  test('forwards provenance to NEXUS and exposes gate audit to Mission Control', async (): Promise<void> => {
    const engine = new FakeEngine(true, allPassDecision());
    const provider = new FakeEvidenceProvider({
      interactiveMissionsAvailable: true,
      researchMissionsAvailable: true,
      configuredProviders: ['fixture-provider'],
    }, {
      evidence: evidence(),
      verificationNote: 'Evidence bundle verified.',
      draftResponses: [{ agent: 'fixture-agent', text: 'Draft', verified: true }],
      audit: [{ stage: 'provider', detail: 'Evidence collected.' }],
    });

    const executor = new NexusMissionExecutor(engine, provider);
    const result = await executor.execute({
      runId: 'run-1',
      question: 'Should this pass?',
      mode: 'research',
    });

    expect(result.nexusFinalValue).toBe('YES');
    expect(result.verificationNote).toContain('Evidence bundle verified.');
    expect(result.verificationNote).toContain('All canonical gates passed.');
    expect(result.evidence).toEqual([
      expect.objectContaining({
        id: 'e1',
        verified: true,
        citation: 'fixture://e1',
        stance: 'support',
        trustBoundary: 'fixture-boundary',
      }),
    ]);
    expect(result.audit).toEqual(expect.arrayContaining([
      { stage: 'nexus_gate:grand_council', detail: 'PASS' },
      { stage: 'nexus_gate:verifier', detail: 'PASS' },
    ]));
    expect(engine.requests[0]).toMatchObject({
      runId: 'run-1',
      question: 'Should this pass?',
      evidence: expect.arrayContaining([expect.objectContaining({ id: 'e1' })]),
    });
  });

  test('converts raw YES to mobile NO when canonical approval is false', async (): Promise<void> => {
    const engine = new FakeEngine(true, allPassDecision({
      decision: 'YES',
      approved: false,
      pipelinePasses: {
        grand_council: true,
        neis: true,
        blinded_dissent: false,
        verifier: true,
      },
      reasons: ['Blinded dissent did not pass.'],
    }));
    const provider = new FakeEvidenceProvider({
      interactiveMissionsAvailable: true,
      researchMissionsAvailable: true,
      configuredProviders: ['fixture-provider'],
    }, { evidence: evidence() });

    const executor = new NexusMissionExecutor(engine, provider);
    const result = await executor.execute({
      runId: 'run-2',
      question: 'Should this fail closed?',
      mode: 'ask',
    });

    expect(result.nexusFinalValue).toBe('NO');
    expect(result.audit).toContainEqual({
      stage: 'nexus_gate:blinded_dissent',
      detail: 'FAIL',
    });
  });

  test('fails before NEXUS when evidence is unavailable', async (): Promise<void> => {
    const engine = new FakeEngine(true, allPassDecision());
    const executor = new NexusMissionExecutor(engine, new UnavailableMissionEvidenceProvider());

    await expect(executor.execute({
      runId: 'run-3',
      question: 'No evidence',
      mode: 'ask',
    })).rejects.toThrow('not ready');
    expect(engine.requests).toHaveLength(0);
  });
});
