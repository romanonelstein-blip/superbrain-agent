import { createHash, randomUUID } from 'node:crypto';
import { assessSkillCandidate, type SkillCandidate } from './skill-foundry.js';
import type { NexusDecisionRequest, NexusEvidenceInput } from './nexus.js';
import type { NexusDecisionEngine, MissionEvidenceProvider } from '../mobile/nexus-mission-executor.js';
import type { MasterDecisionAction, MissionMode } from '../mobile/mission-control.js';

// This runtime dispatches only explicitly registered, trusted read-only handlers.
// A SKILL.md file is NEVER executable code or permission to call tools.
const AGENT_ID = /^[a-z][a-z0-9-]{1,63}$/;
const ALL_GATES = ['grand_council', 'neis', 'blinded_dissent', 'verifier'] as const;
const MAX_PLAN_MS = 5 * 60_000;

export interface SkillAgentBinding {
  agentId: string;
  candidate: SkillCandidate;
  // Handler is application code supplied by an operator, not loaded from skill text.
  handle: (input: Readonly<SkillRuntimeInput>) => Promise<SkillRuntimeOutput>;
}

export interface SkillRuntimeInput {
  workspaceId: string;
  agentId: string;
  skillName: string;
  runId: string;
  question: string;
  mode: MissionMode;
}

export interface SkillRuntimeOutput {
  summary: string;
  evidenceIds: string[];
}

export interface SkillRuntimePlan {
  planId: string;
  intentDigest: string;
  workspaceId: string;
  agentId: string;
  skillName: string;
  runId: string;
  skillDigest: string;
  evidenceDigest: string;
  expiresAt: string;
  state: 'awaiting-master';
}

export interface SkillMasterAuthorization {
  action: MasterDecisionAction;
  actorId: string;
  workspaceId: string;
  planId: string;
  intentDigest: string;
  expiresAt: string;
  // Opaque proof checked by a real server-side authority. NOT an API bearer token.
  proof: string;
}

export interface SkillMasterVerifier {
  verify(authorization: Readonly<SkillMasterAuthorization>): Promise<boolean>;
}

export interface SkillRuntimeAuditRecord {
  event: 'registered' | 'prepared' | 'approved' | 'denied' | 'claimed' | 'completed' | 'failed';
  planId?: string;
  agentId: string;
  skillName: string;
  workspaceId?: string;
  intentDigest?: string;
  actorId?: string;
}

export interface SkillRuntimeAuditSink {
  append(record: Readonly<SkillRuntimeAuditRecord>): Promise<void>;
}

interface SkillBindingRecord {
  agentId: string;
  skillName: string;
  skillDigest: string;
  revision: string;
  handle: SkillAgentBinding['handle'];
}

interface SkillPlanRecord {
  plan: SkillRuntimePlan;
  request: SkillRuntimeInput;
  evidenceIds: string[];
  authorization: SkillMasterAuthorization | null;
  state: 'prepared' | 'approved' | 'claimed' | 'completed' | 'failed';
}

const digest = (payload: unknown): string =>
  createHash('sha256').update(JSON.stringify(payload)).digest('hex');

function verifyEvidence(items: NexusEvidenceInput[]): void {
  if (items.length === 0) throw new Error('Skill evaluation needs evidence.');
  const ids = new Set<string>();
  for (const item of items) {
    if (ids.has(item.id) || !item.id.trim() || !item.sourceId.trim() ||
        !item.sourceFamily.trim() || !item.claim.trim() || item.verified !== true ||
        !item.citation?.trim() || !item.contentHash?.trim()) {
      throw new Error('Skill evidence is incomplete, unverified, or duplicated.');
    }
    ids.add(item.id);
  }
}

export class SkillRuntime {
  private readonly bindings = new Map<string, SkillBindingRecord>();
  private readonly plans = new Map<string, SkillPlanRecord>();

  constructor(
    private readonly nexus: NexusDecisionEngine,
    private readonly evidenceProvider: MissionEvidenceProvider,
    private readonly masterVerifier: SkillMasterVerifier,
    private readonly audit: SkillRuntimeAuditSink,
    private readonly now: () => number = Date.now,
  ) {}

  listAgents(): Array<{ agentId: string; skillName: string; skillDigest: string }> {
    return [...this.bindings.values()].map(({ agentId, skillName, skillDigest }) => ({
      agentId, skillName, skillDigest,
    }));
  }

  async register(binding: SkillAgentBinding): Promise<void> {
    if (!AGENT_ID.test(binding.agentId) || typeof binding.handle !== 'function') {
      throw new Error('Invalid trusted agent binding.');
    }
    const result = assessSkillCandidate(binding.candidate);
    if (result.state !== 'review-ready' || !result.manifest ||
        result.requestedCapabilities.length !== 1 || result.requestedCapabilities[0] !== 'read-workspace') {
      throw new Error('Skill is not eligible for the read-only runtime.');
    }
    const key = this.key(binding.agentId, result.manifest.name);
    if (this.bindings.has(key)) throw new Error('Skill agent is already registered.');
    const record: SkillBindingRecord = {
      agentId: binding.agentId,
      skillName: result.manifest.name,
      skillDigest: result.contentSha256,
      revision: binding.candidate.sourceRevision,
      handle: binding.handle,
    };
    await this.audit.append({
      event: 'registered', agentId: record.agentId, skillName: record.skillName,
    });
    this.bindings.set(key, record);
  }

  async prepare(input: SkillRuntimeInput): Promise<SkillRuntimePlan> {
    const binding = this.bindings.get(this.key(input.agentId, input.skillName));
    if (!binding) throw new Error('Skill agent is not registered.');
    if (!input.workspaceId.trim() || !input.runId.trim() ||
        !input.question.trim() || input.question.length > 20_000 ||
        !['ask', 'research'].includes(input.mode)) {
      throw new Error('Invalid skill request.');
    }
    const [status, provider] = await Promise.all([this.nexus.getStatus(), this.evidenceProvider.getStatus()]);
    const available = input.mode === 'research' ?
      provider.researchMissionsAvailable : provider.interactiveMissionsAvailable;
    if (!status.ready || !available) throw new Error('NEXUS or skill evidence provider is not ready.');

    const bundle = await this.evidenceProvider.collect(input);
    verifyEvidence(bundle.evidence);
    if (!bundle.dissent?.completed || !bundle.dissent.provider.trim()) {
      throw new Error('Independent dissent is required.');
    }
    verifyEvidence(bundle.dissent.evidence);

    const evaluation: NexusDecisionRequest = {
      question: input.question,
      runId: input.runId,
      evidence: bundle.evidence,
      dissent: bundle.dissent,
    };
    const decision = await this.nexus.evaluate(evaluation);
    const availableIds = new Set(bundle.evidence.map(item => item.id));
    if (!decision.approved || decision.decision !== 'YES' ||
        !ALL_GATES.every(gate => decision.pipelinePasses[gate] === true) ||
        decision.evidenceIds.length === 0 ||
        decision.evidenceIds.some(id => !availableIds.has(id))) {
      throw new Error('Canonical NEXUS approval and evidence gates are required.');
    }

    const evidenceDigest = digest({
      evidence: bundle.evidence.map(item => [item.id, item.sourceId, item.contentHash]),
      dissent: bundle.dissent.evidence.map(item => [item.id, item.sourceId, item.contentHash]),
      decisionEvidenceIds: [...decision.evidenceIds].sort(),
    });
    const requested = { ...input };
    const intentDigest = digest({
      request: requested, skillDigest: binding.skillDigest, revision: binding.revision,
      evidenceDigest, gates: decision.pipelinePasses,
    });
    const plan: SkillRuntimePlan = {
      planId: randomUUID(), intentDigest, workspaceId: input.workspaceId,
      agentId: input.agentId, skillName: input.skillName, runId: input.runId,
      skillDigest: binding.skillDigest, evidenceDigest,
      expiresAt: new Date(this.now() + MAX_PLAN_MS).toISOString(),
      state: 'awaiting-master',
    };
    await this.audit.append({
      event: 'prepared', planId: plan.planId, agentId: plan.agentId,
      skillName: plan.skillName, workspaceId: plan.workspaceId, intentDigest,
    });
    this.plans.set(plan.planId, {
      plan, request: requested, evidenceIds: [...decision.evidenceIds],
      authorization: null, state: 'prepared',
    });
    return { ...plan };
  }

  async approve(planId: string, approval: SkillMasterAuthorization): Promise<void> {
    const record = this.plans.get(planId);
    if (!record || record.state !== 'prepared') throw new Error('Unknown or non-pending skill plan.');
    this.assertNotExpired(record.plan.expiresAt);
    const correctIntent =
      approval.action === 'ACCEPT' && approval.planId === record.plan.planId &&
      approval.workspaceId === record.plan.workspaceId &&
      approval.intentDigest === record.plan.intentDigest &&
      approval.actorId.trim().length > 0 && approval.proof.trim().length > 0;
    if (!correctIntent || !Number.isFinite(Date.parse(approval.expiresAt)) ||
        Date.parse(approval.expiresAt) <= this.now() ||
        Date.parse(approval.expiresAt) > Date.parse(record.plan.expiresAt)) {
      throw new Error('Master approval is not bound to the exact current skill intent.');
    }
    // A generic Mission Control ACCEPT note is insufficient: its actor,
    // cryptographic proof and exact content digest were never verified.
    if (!await this.masterVerifier.verify({ ...approval })) {
      throw new Error('Master approval authority rejected the proof.');
    }
    await this.audit.append({
      event: 'approved', planId, agentId: record.plan.agentId,
      skillName: record.plan.skillName, workspaceId: record.plan.workspaceId,
      intentDigest: record.plan.intentDigest, actorId: approval.actorId,
    });
    record.authorization = { ...approval };
    record.state = 'approved';
  }

  async execute(planId: string): Promise<SkillRuntimeOutput> {
    const record = this.plans.get(planId);
    if (!record || record.state !== 'approved' || !record.authorization) {
      throw new Error('Skill plan has no unused Master approval.');
    }
    this.assertNotExpired(record.plan.expiresAt);
    this.assertNotExpired(record.authorization.expiresAt);
    const binding = this.bindings.get(this.key(record.plan.agentId, record.plan.skillName));
    if (!binding || binding.skillDigest !== record.plan.skillDigest) {
      throw new Error('Registered skill has changed since review.');
    }
    // The audit claim MUST succeed before the handler runs. Claim is set
    // synchronously before the first await, blocking concurrent/replayed calls.
    record.state = 'claimed';
    try {
      await this.audit.append({
        event: 'claimed', planId, agentId: record.plan.agentId,
        skillName: record.plan.skillName, workspaceId: record.plan.workspaceId,
        intentDigest: record.plan.intentDigest, actorId: record.authorization.actorId,
      });
    } catch {
      record.state = 'failed';
      throw new Error('Skill execution blocked: audit claim unavailable.');
    }

    try {
      const output = await binding.handle(Object.freeze({ ...record.request }));
      if (!output || !output.summary?.trim() || !Array.isArray(output.evidenceIds) ||
          output.evidenceIds.some(id => !record.evidenceIds.includes(id))) {
        throw new Error('Skill handler output lacks authorized evidence.');
      }
      await this.audit.append({
        event: 'completed', planId, agentId: record.plan.agentId,
        skillName: record.plan.skillName, workspaceId: record.plan.workspaceId,
        intentDigest: record.plan.intentDigest,
      });
      record.state = 'completed';
      return { summary: output.summary, evidenceIds: [...output.evidenceIds] };
    } catch {
      record.state = 'failed';
      throw new Error('Skill execution failed closed; no retry or approval reuse allowed.');
    }
  }

  private key(agentId: string, skillName: string): string {
    return agentId + ':' + skillName;
  }

  private assertNotExpired(value: string): void {
    if (!Number.isFinite(Date.parse(value)) || Date.parse(value) <= this.now()) {
      throw new Error('Skill plan or approval has expired.');
    }
  }
}
