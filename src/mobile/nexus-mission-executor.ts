import { NexusBridge } from '../core/nexus.js';
import type {
  NexusBridgeStatus,
  NexusDecision,
  NexusDecisionRequest,
  NexusDissentInput,
  NexusEvidenceInput,
} from '../core/nexus.js';
import type {
  MissionAuditItem,
  MissionDraft,
  MissionEvidence,
  MissionExecutionInput,
  MissionExecutionResult,
  MissionExecutor,
  MissionExecutorStatus,
} from './mission-control.js';

export interface NexusDecisionEngine {
  getStatus(): Promise<NexusBridgeStatus>;
  evaluate(request: NexusDecisionRequest): Promise<NexusDecision>;
}

export interface MissionEvidenceProviderStatus {
  interactiveMissionsAvailable: boolean;
  researchMissionsAvailable: boolean;
  configuredProviders: string[];
}

export interface MissionEvidenceBundle {
  evidence: NexusEvidenceInput[];
  dissent?: NexusDissentInput;
  draftResponses?: MissionDraft[];
  audit?: MissionAuditItem[];
  verificationNote?: string;
}

export interface MissionEvidenceProvider {
  getStatus(): Promise<MissionEvidenceProviderStatus>;
  collect(input: MissionExecutionInput): Promise<MissionEvidenceBundle>;
}

export class UnavailableMissionEvidenceProvider implements MissionEvidenceProvider {
  async getStatus(): Promise<MissionEvidenceProviderStatus> {
    return {
      interactiveMissionsAvailable: false,
      researchMissionsAvailable: false,
      configuredProviders: [],
    };
  }

  async collect(input: MissionExecutionInput): Promise<MissionEvidenceBundle> {
    void input;
    throw new Error('No mission evidence provider is configured.');
  }
}

export class NexusMissionExecutor implements MissionExecutor {
  private readonly engine: NexusDecisionEngine;
  private readonly evidenceProvider: MissionEvidenceProvider;

  constructor(
    engine: NexusDecisionEngine = new NexusBridge(),
    evidenceProvider: MissionEvidenceProvider = new UnavailableMissionEvidenceProvider(),
  ) {
    this.engine = engine;
    this.evidenceProvider = evidenceProvider;
  }

  async getStatus(): Promise<MissionExecutorStatus> {
    const [nexus, evidence] = await Promise.all([
      this.engine.getStatus(),
      this.evidenceProvider.getStatus(),
    ]);
    return {
      interactiveMissionsAvailable: nexus.ready && evidence.interactiveMissionsAvailable,
      researchMissionsAvailable: nexus.ready && evidence.researchMissionsAvailable,
      configuredProviders: evidence.configuredProviders,
    };
  }

  async execute(input: MissionExecutionInput): Promise<MissionExecutionResult> {
    const status = await this.getStatus();
    const available = input.mode === 'research'
      ? status.researchMissionsAvailable
      : status.interactiveMissionsAvailable;
    if (!available) throw new Error('NEXUS mission execution is not ready.');

    const bundle = await this.evidenceProvider.collect(input);
    if (bundle.evidence.length === 0) {
      throw new Error('NEXUS mission execution requires evidence.');
    }

    const decision = await this.engine.evaluate({
      question: input.question,
      evidence: bundle.evidence,
      ...(bundle.dissent ? { dissent: bundle.dissent } : {}),
      runId: input.runId,
    });

    const evidence: MissionEvidence[] = bundle.evidence.map((item): MissionEvidence => ({
      id: item.id,
      claim: item.claim,
      verified: item.verified === true,
      sourceId: item.sourceId,
      sourceFamily: item.sourceFamily,
      ...(item.citation ? { citation: item.citation } : {}),
      ...(item.stance ? { stance: item.stance } : {}),
    }));

    const gateAudit: MissionAuditItem[] = Object.entries(decision.pipelinePasses)
      .map(([gate, passed]): MissionAuditItem => ({
        stage: `nexus_gate:${gate}`,
        detail: passed ? 'PASS' : 'FAIL',
      }));

    const verificationParts = [
      bundle.verificationNote?.trim(),
      ...decision.reasons.map((reason): string => reason.trim()).filter(Boolean),
    ].filter((item): item is string => Boolean(item));

    return {
      nexusFinalValue: decision.approved ? 'YES' : 'NO',
      ...(verificationParts.length > 0 ? { verificationNote: verificationParts.join(' | ') } : {}),
      ...(bundle.draftResponses ? { draftResponses: bundle.draftResponses } : {}),
      evidence,
      audit: [
        ...(bundle.audit ?? []),
        ...gateAudit,
        {
          stage: 'nexus_decision',
          detail: `Raw=${decision.decision}; approved=${decision.approved}; evidence=${decision.evidenceIds.length}`,
        },
      ],
    };
  }
}
