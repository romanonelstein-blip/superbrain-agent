import { access } from 'node:fs/promises';
import path from 'node:path';
import { execa } from 'execa';

const REQUIRED_GATES = ['grand_council', 'neis', 'blinded_dissent', 'verifier'] as const;

export type NexusStance = 'support' | 'challenge' | 'neutral';

export interface NexusEvidenceInput {
  id: string;
  claim: string;
  stance?: NexusStance;
  sourceId: string;
  sourceFamily: string;
  reliability?: number;
  freshness?: number;
  relevance?: number;
  verified?: boolean;
  citation?: string;
  contentHash?: string;
  retrievedAt?: string;
  location?: string;
  contentType?: string;
  provider?: string;
  providerModel?: string;
  providerRequestId?: string;
  providerAgent?: string;
  providerAttempts?: number;
  providerLatencyMs?: number;
}

export interface NexusDissentInput {
  completed: true;
  provider: string;
  requestId?: string;
  evidence: NexusEvidenceInput[];
}

export interface NexusDecisionRequest {
  question: string;
  evidence: NexusEvidenceInput[];
  dissent?: NexusDissentInput;
  runId?: string;
}

export interface NexusDecision {
  decision: 'YES' | 'NO';
  approved: boolean;
  pipelinePasses: Record<(typeof REQUIRED_GATES)[number], boolean>;
  reasons: string[];
  evidenceIds: string[];
}

export interface NexusBridgeStatus {
  configured: boolean;
  ready: boolean;
  corePath: string | null;
  error: string | null;
}

export interface NexusBridgeConfig {
  corePath?: string;
  pythonCommand?: string;
  runnerPath?: string;
  timeoutMs?: number;
}

interface RawNexusDecision {
  decision?: unknown;
  approved?: unknown;
  pipelinePasses?: unknown;
  reasons?: unknown;
  evidenceIds?: unknown;
}

export class NexusBridge {
  private readonly corePath: string | null;
  private readonly pythonCommand: string;
  private readonly runnerPath: string;
  private readonly timeoutMs: number;

  constructor(config: NexusBridgeConfig = {}) {
    const configuredPath = config.corePath ?? process.env.SUPERBRAIN_NEXUS_ROOT ?? null;
    this.corePath = configuredPath ? path.resolve(configuredPath) : null;
    this.pythonCommand = config.pythonCommand ?? process.env.SUPERBRAIN_PYTHON ?? 'python';
    this.runnerPath = config.runnerPath ?? path.resolve(process.cwd(), 'python', 'nexus_bridge_runner.py');
    this.timeoutMs = config.timeoutMs ?? 30000;
  }

  async getStatus(): Promise<NexusBridgeStatus> {
    if (!this.corePath) {
      return { configured: false, ready: false, corePath: null, error: 'SUPERBRAIN_NEXUS_ROOT is not configured.' };
    }
    try {
      await Promise.all([
        access(path.join(this.corePath, 'nexus1000', 'orchestrator.py')),
        access(path.join(this.corePath, 'nexus1000', 'neis.py')),
        access(this.runnerPath),
      ]);
      return { configured: true, ready: true, corePath: this.corePath, error: null };
    } catch {
      return {
        configured: true,
        ready: false,
        corePath: this.corePath,
        error: 'NEXUS core or bridge runner is unavailable.',
      };
    }
  }

  async evaluate(request: NexusDecisionRequest): Promise<NexusDecision> {
    const status = await this.getStatus();
    if (!status.ready || !this.corePath) {
      throw new Error(status.error ?? 'NEXUS bridge is unavailable.');
    }
    this.validateRequest(request);

    const payload = JSON.stringify({
      corePath: this.corePath,
      question: request.question,
      evidence: request.evidence,
      ...(request.dissent ? { dissent: request.dissent } : {}),
      ...(request.runId ? { runId: request.runId } : {}),
    });

    try {
      const { stdout } = await execa(this.pythonCommand, [this.runnerPath], {
        input: payload,
        timeout: this.timeoutMs,
        reject: true,
        maxBuffer: 1024 * 1024,
      });
      return this.parseDecision(stdout);
    } catch {
      throw new Error('NEXUS evaluation failed or timed out. No approval was granted.');
    }
  }

  private validateRequest(request: NexusDecisionRequest): void {
    if (!request.question.trim()) throw new Error('NEXUS question must be non-empty.');
    if (request.evidence.length === 0) throw new Error('NEXUS requires evidence.');
    for (const item of request.evidence) this.validateEvidence(item);
    if (request.dissent) {
      if (!request.dissent.provider.trim()) throw new Error('NEXUS dissent provider must be non-empty.');
      for (const item of request.dissent.evidence) this.validateEvidence(item);
    }
  }

  private validateEvidence(item: NexusEvidenceInput): void {
    if (!item.id.trim() || !item.claim.trim() || !item.sourceId.trim() || !item.sourceFamily.trim()) {
      throw new Error('NEXUS evidence is missing required provenance fields.');
    }
    if (item.verified === true && (!item.citation?.trim() || !item.contentHash?.trim())) {
      throw new Error('Verified NEXUS evidence requires citation and contentHash.');
    }
  }

  private parseDecision(stdout: string): NexusDecision {
    let raw: RawNexusDecision;
    try {
      raw = JSON.parse(stdout) as RawNexusDecision;
    } catch {
      throw new Error('NEXUS returned invalid JSON.');
    }

    const passes = raw.pipelinePasses;
    if (!passes || typeof passes !== 'object') throw new Error('NEXUS decision is missing pipeline gates.');
    const record = passes as Record<string, unknown>;
    const pipelinePasses = {
      grand_council: record.grand_council === true,
      neis: record.neis === true,
      blinded_dissent: record.blinded_dissent === true,
      verifier: record.verifier === true,
    };
    const decision = raw.decision === 'YES' ? 'YES' : 'NO';
    const approved = raw.approved === true && decision === 'YES' && REQUIRED_GATES.every(gate => pipelinePasses[gate]);
    const reasons = Array.isArray(raw.reasons) ? raw.reasons.filter((item): item is string => typeof item === 'string') : [];
    const evidenceIds = Array.isArray(raw.evidenceIds)
      ? raw.evidenceIds.filter((item): item is string => typeof item === 'string')
      : [];

    return { decision, approved, pipelinePasses, reasons, evidenceIds };
  }
}
