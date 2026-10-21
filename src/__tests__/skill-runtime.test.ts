import { createHash } from 'node:crypto';
import type { SkillCandidate } from '../core/skill-foundry';
import {
  SkillRuntime,
  type SkillMasterAuthorization,
  type SkillRuntimeAuditRecord,
  type SkillRuntimeAuditSink,
} from '../core/skill-runtime';
import type { NexusDecision, NexusDecisionRequest, NexusBridgeStatus, NexusEvidenceInput } from '../core/nexus';
import type {
  NexusDecisionEngine, MissionEvidenceProvider, MissionEvidenceBundle,
  MissionEvidenceProviderStatus,
} from '../mobile/nexus-mission-executor';
import type { MissionExecutionInput } from '../mobile/mission-control';

const skillMarkdown = [
  '---',
  'name: nexus-evidence-verification',
  'description: Only summarize already confirmed provenance with read-only capabilities.',
  '---',
  '# Verified skill',
  'Return referenced evidence without making side-effectful calls.',
  '',
].join('\n');

function candidate(changes: Partial<SkillCandidate> = {}): SkillCandidate {
  return {
    directoryName: 'nexus-evidence-verification',
    skillMarkdown,
    sourceUrl: 'https://github.com/example/trusted-skill',
    sourceRevision: 'a'.repeat(40),
    expectedSha256: createHash('sha256').update(skillMarkdown).digest('hex'),
    requestedCapabilities: ['read-workspace'],
    ...changes,
  };
}

function evidence(id = 'evidence-1'): NexusEvidenceInput {
  return {
    id, claim: 'Verified fixture with source and timestamp',
    sourceId: 'fixture:' + id, sourceFamily: 'test-independent-source',
    verified: true, citation: 'fixture://' + id,
    contentHash: createHash('sha256').update(id).digest('hex'),
  };
}

const positiveDecision = (): NexusDecision => ({
  decision: 'YES', approved: true,
  evidenceIds: ['evidence-1'], reasons: ['Canonical gates passed'],
  pipelinePasses: {
    grand_council: true, neis: true, blinded_dissent: true, verifier: true,
  },
});

class Engine implements NexusDecisionEngine {
  requests: NexusDecisionRequest[] = [];
  ready = true;
  decision: NexusDecision = positiveDecision();

  async getStatus(): Promise<NexusBridgeStatus> {
    return { configured: this.ready, ready: this.ready, corePath: this.ready ? '/fixture' : null, error: null };
  }
  async evaluate(input: NexusDecisionRequest): Promise<NexusDecision> {
    this.requests.push(input);
    return this.decision;
  }
}

class Provider implements MissionEvidenceProvider {
  enabled = true;
  bundle: MissionEvidenceBundle = {
    evidence: [evidence()],
    dissent: { completed: true, provider: 'dissent-fixture', evidence: [evidence('dissent-1')] },
  };
  async getStatus(): Promise<MissionEvidenceProviderStatus> {
    return {
      interactiveMissionsAvailable: this.enabled,
      researchMissionsAvailable: this.enabled,
      configuredProviders: ['fixture'],
    };
  }
  async collect(input: MissionExecutionInput): Promise<MissionEvidenceBundle> {
    void input;
    return this.bundle;
  }
}

const input = {
  agentId: 'research-agent',
  skillName: 'nexus-evidence-verification',
  workspaceId: 'workspace-a',
  runId: 'run-a',
  question: 'Is this verified?',
  mode: 'research' as const,
};

describe('SkillRuntime approval and NEXUS integration', () => {
  let clock: number;
  let engine: Engine;
  let provider: Provider;
  let audit: SkillRuntimeAuditRecord[];
  let runtime: SkillRuntime;
  let handler: jest.Mock;
  let canVerify: boolean;
  let failAudit: boolean;

  beforeEach(async () => {
    clock = Date.parse('2026-10-21T12:00:00Z');
    engine = new Engine();
    provider = new Provider();
    audit = [];
    canVerify = true;
    failAudit = false;
    handler = jest.fn(async () => ({
      summary: 'Fixture answer only', evidenceIds: ['evidence-1'],
    }));
    const sink: SkillRuntimeAuditSink = {
      append: async (item) => {
        if (failAudit) throw new Error('audit unavailable');
        audit.push({ ...item });
      },
    };
    runtime = new SkillRuntime(engine, provider, {
      verify: async () => canVerify,
    }, sink, () => clock);
    await runtime.register({
      agentId: 'research-agent', candidate: candidate(), handle: handler,
    });
  });

  async function prepareAndApprove(overrides: Partial<SkillMasterAuthorization> = {}) {
    const plan = await runtime.prepare(input);
    const proof: SkillMasterAuthorization = {
      action: 'ACCEPT',
      planId: plan.planId,
      intentDigest: plan.intentDigest,
      workspaceId: 'workspace-a',
      actorId: 'human-master',
      proof: 'opaque-signature-from-authority',
      expiresAt: new Date(clock + 60_000).toISOString(),
      ...overrides,
    };
    await runtime.approve(plan.planId, proof);
    return plan;
  }

  test('registers trusted skill to explicit agent; registration alone never runs handler', () => {
    expect(runtime.listAgents()).toEqual([expect.objectContaining({
      agentId: 'research-agent', skillName: 'nexus-evidence-verification',
    })]);
    expect(handler).not.toHaveBeenCalled();
  });

  test('passes actual evidence and independent dissent to NEXUS before approval', async () => {
    const plan = await runtime.prepare(input);
    expect(plan.state).toBe('awaiting-master');
    expect(plan.evidenceDigest).toMatch(/^[a-f0-9]{64}$/);
    expect(engine.requests).toHaveLength(1);
    expect(engine.requests[0]).toMatchObject({
      runId: 'run-a', question: input.question,
      evidence: [expect.objectContaining({ id: 'evidence-1' })],
      dissent: { completed: true, provider: 'dissent-fixture' },
    });
    await expect(runtime.execute(plan.planId)).rejects.toThrow('no unused Master approval');
    expect(handler).not.toHaveBeenCalled();
  });

  test('executes one trusted, read-only handler only after exact verified Master grant', async () => {
    const plan = await prepareAndApprove();
    const outcome = await runtime.execute(plan.planId);
    expect(outcome).toEqual({ summary: 'Fixture answer only', evidenceIds: ['evidence-1'] });
    expect(handler).toHaveBeenCalledTimes(1);
    expect(audit.map(a => a.event)).toEqual([
      'registered', 'prepared', 'approved', 'claimed', 'completed',
    ]);
    await expect(runtime.execute(plan.planId)).rejects.toThrow('no unused Master approval');
  });

  test.each([
    ['wrong tenant', { workspaceId: 'workspace-b' }],
    ['changed intent digest', { intentDigest: 'tampered' }],
    ['wrong plan', { planId: 'unrelated' }],
    ['wrong action', { action: 'OVERRIDE' as const }],
    ['missing actor', { actorId: '' }],
    ['missing proof', { proof: '' }],
  ])('blocks %s from reusing unrelated Master approval', async (_, changes) => {
    const plan = await runtime.prepare(input);
    await expect(runtime.approve(plan.planId, {
      action: 'ACCEPT', workspaceId: 'workspace-a',
      planId: plan.planId, intentDigest: plan.intentDigest,
      actorId: 'human-master', proof: 'signed',
      expiresAt: new Date(clock + 60_000).toISOString(),
      ...changes,
    })).rejects.toThrow();
    expect(handler).not.toHaveBeenCalled();
  });

  test('never treats a fabricated approval as permission when authority denies it', async () => {
    canVerify = false;
    const plan = await runtime.prepare(input);
    await expect(runtime.approve(plan.planId, {
      action: 'ACCEPT', workspaceId: 'workspace-a',
      planId: plan.planId, intentDigest: plan.intentDigest,
      actorId: 'human-master', proof: 'unverifiable',
      expiresAt: new Date(clock + 60_000).toISOString(),
    })).rejects.toThrow('authority rejected');
    expect(handler).not.toHaveBeenCalled();
  });

  test('fails closed when NEXUS runtime is missing or verdict is noncanonical', async () => {
    engine.ready = false;
    await expect(runtime.prepare(input)).rejects.toThrow('not ready');
    engine.ready = true;
    engine.decision = { ...positiveDecision(), pipelinePasses: { ...positiveDecision().pipelinePasses, neis: false } };
    await expect(runtime.prepare(input)).rejects.toThrow('canonical NEXUS');
    expect(handler).not.toHaveBeenCalled();
  });

  test('rejects missing verified evidence or independent dissent without calling NEXUS', async () => {
    provider.bundle = { evidence: [{ ...evidence(), citation: undefined }] };
    await expect(runtime.prepare(input)).rejects.toThrow('incomplete');
    expect(engine.requests).toHaveLength(0);
    provider.bundle = { evidence: [evidence()] };
    await expect(runtime.prepare(input)).rejects.toThrow('Independent dissent');
    expect(engine.requests).toHaveLength(0);
  });

  test('blocks expired plans and expired Master approval', async () => {
    const plan = await prepareAndApprove();
    clock += 70_000;
    await expect(runtime.execute(plan.planId)).rejects.toThrow('expired');
    expect(handler).not.toHaveBeenCalled();
    const nextPlan = await runtime.prepare({ ...input, runId: 'run-b' });
    clock += 5 * 60_000 + 1;
    await expect(runtime.approve(nextPlan.planId, {
      action: 'ACCEPT', workspaceId: 'workspace-a',
      planId: nextPlan.planId, intentDigest: nextPlan.intentDigest,
      actorId: 'human-master', proof: 'signed',
      expiresAt: new Date(clock + 30_000).toISOString(),
    })).rejects.toThrow('expired');
  });

  test('claims once before async handler so concurrent execution cannot run twice', async () => {
    let release!: () => void;
    const waiting = new Promise<void>(resolve => { release = resolve; });
    handler.mockImplementation(async () => {
      await waiting;
      return { summary: 'Complete', evidenceIds: ['evidence-1'] };
    });
    const plan = await prepareAndApprove();
    const first = runtime.execute(plan.planId);
    await expect(runtime.execute(plan.planId)).rejects.toThrow('no unused Master approval');
    release();
    await first;
    expect(handler).toHaveBeenCalledTimes(1);
  });

  test('audit outage blocks dispatch, and never silently permits retries', async () => {
    const plan = await prepareAndApprove();
    failAudit = true;
    await expect(runtime.execute(plan.planId)).rejects.toThrow('audit claim unavailable');
    expect(handler).not.toHaveBeenCalled();
    failAudit = false;
    await expect(runtime.execute(plan.planId)).rejects.toThrow('no unused Master approval');
  });

  test('rejects elevated or tampered skill admission before binding', async () => {
    await expect(runtime.register({
      agentId: 'untrusted-agent',
      candidate: candidate({ requestedCapabilities: ['read-workspace', 'external-write'] }),
      handle: handler,
    })).rejects.toThrow('not eligible');
    await expect(runtime.register({
      agentId: 'untrusted-agent',
      candidate: candidate({ expectedSha256: '0'.repeat(64) }),
      handle: handler,
    })).rejects.toThrow('not eligible');
    expect(handler).not.toHaveBeenCalled();
  });

  test('refuses unexpected evidence IDs returned by the handler', async () => {
    handler.mockResolvedValue({ summary: 'Wrong cited evidence', evidenceIds: ['fabricated'] });
    const plan = await prepareAndApprove();
    await expect(runtime.execute(plan.planId)).rejects.toThrow('failed closed');
    await expect(runtime.execute(plan.planId)).rejects.toThrow('no unused Master approval');
  });
});
