import { createHash } from 'node:crypto';

export type RealityDriftState = 'STABLE' | 'WATCH' | 'DRIFT' | 'CRITICAL';
export type RealitySignalDirection = 'CONFIRMS' | 'CONTRADICTS' | 'UNKNOWN';

export interface PredictionAssumption {
  id: string;
  statement: string;
  weight: number;
  critical?: boolean;
}

export interface PredictionContract {
  id: string;
  decision: string;
  createdAt: string;
  assumptions: PredictionAssumption[];
}

export interface RealitySignal {
  id: string;
  assumptionId: string;
  direction: RealitySignalDirection;
  strength: number;
  verified: boolean;
  evidenceId?: string;
  observedAt?: string;
}

export interface RealitySentinelAuditItem {
  stage: string;
  detail: string;
}

export interface RealitySentinelAssessment {
  contractId: string;
  contractHash: string;
  driftScore: number;
  state: RealityDriftState;
  reanalyze: boolean;
  brokenAssumptionIds: string[];
  confirmedAssumptionIds: string[];
  ignoredSignalIds: string[];
  reasons: string[];
  audit: RealitySentinelAuditItem[];
}

export interface RealitySentinelConfig {
  watchThreshold?: number;
  driftThreshold?: number;
  criticalThreshold?: number;
  brokenAssumptionThreshold?: number;
  criticalAssumptionThreshold?: number;
}

interface AssumptionSignalSummary {
  strongestContradiction: number;
  strongestConfirmation: number;
}

const DEFAULTS: Required<RealitySentinelConfig> = {
  watchThreshold: 15,
  driftThreshold: 35,
  criticalThreshold: 65,
  brokenAssumptionThreshold: 60,
  criticalAssumptionThreshold: 80,
};

function assertIntegerRange(name: string, value: number, min: number, max: number): void {
  if (!Number.isInteger(value) || value < min || value > max) {
    throw new Error(`${name} must be an integer between ${min} and ${max}.`);
  }
}

function validateContract(contract: PredictionContract): void {
  if (!contract.id.trim()) throw new Error('Prediction contract id is required.');
  if (!contract.decision.trim()) throw new Error('Prediction contract decision is required.');
  if (!contract.createdAt.trim()) throw new Error('Prediction contract createdAt is required.');
  if (contract.assumptions.length === 0) throw new Error('Prediction contract requires at least one assumption.');

  const seen = new Set<string>();
  for (const assumption of contract.assumptions) {
    if (!assumption.id.trim()) throw new Error('Prediction assumption id is required.');
    if (seen.has(assumption.id)) throw new Error(`Duplicate prediction assumption id: ${assumption.id}`);
    seen.add(assumption.id);
    if (!assumption.statement.trim()) throw new Error(`Prediction assumption ${assumption.id} requires a statement.`);
    assertIntegerRange(`Prediction assumption ${assumption.id} weight`, assumption.weight, 1, 100);
  }
}

function validateConfig(config: Required<RealitySentinelConfig>): void {
  assertIntegerRange('watchThreshold', config.watchThreshold, 1, 100);
  assertIntegerRange('driftThreshold', config.driftThreshold, 1, 100);
  assertIntegerRange('criticalThreshold', config.criticalThreshold, 1, 100);
  assertIntegerRange('brokenAssumptionThreshold', config.brokenAssumptionThreshold, 1, 100);
  assertIntegerRange('criticalAssumptionThreshold', config.criticalAssumptionThreshold, 1, 100);

  if (!(config.watchThreshold < config.driftThreshold && config.driftThreshold < config.criticalThreshold)) {
    throw new Error('Reality Sentinel thresholds must satisfy watch < drift < critical.');
  }
}

function canonicalContractPayload(contract: PredictionContract): string {
  return JSON.stringify({
    id: contract.id,
    decision: contract.decision,
    createdAt: contract.createdAt,
    assumptions: [...contract.assumptions]
      .sort((a, b): number => a.id.localeCompare(b.id))
      .map((assumption) => ({
        id: assumption.id,
        statement: assumption.statement,
        weight: assumption.weight,
        critical: assumption.critical === true,
      })),
  });
}

export function predictionContractHash(contract: PredictionContract): string {
  validateContract(contract);
  return createHash('sha256').update(canonicalContractPayload(contract)).digest('hex');
}

export class RealitySentinel {
  private readonly config: Required<RealitySentinelConfig>;

  constructor(config: RealitySentinelConfig = {}) {
    this.config = { ...DEFAULTS, ...config };
    validateConfig(this.config);
  }

  assess(contract: PredictionContract, signals: RealitySignal[]): RealitySentinelAssessment {
    validateContract(contract);

    const assumptionById = new Map(contract.assumptions.map((assumption) => [assumption.id, assumption]));
    const summaries = new Map<string, AssumptionSignalSummary>();
    const ignoredSignalIds: string[] = [];
    const audit: RealitySentinelAuditItem[] = [];

    for (const assumption of contract.assumptions) {
      summaries.set(assumption.id, { strongestContradiction: 0, strongestConfirmation: 0 });
    }

    for (const signal of signals) {
      assertIntegerRange(`Reality signal ${signal.id} strength`, signal.strength, 0, 100);
      const assumption = assumptionById.get(signal.assumptionId);

      if (!signal.verified) {
        ignoredSignalIds.push(signal.id);
        audit.push({ stage: 'signal_ignored', detail: `${signal.id}: unverified signal` });
        continue;
      }
      if (!assumption) {
        ignoredSignalIds.push(signal.id);
        audit.push({ stage: 'signal_ignored', detail: `${signal.id}: unknown assumption ${signal.assumptionId}` });
        continue;
      }
      if (signal.direction === 'UNKNOWN') {
        ignoredSignalIds.push(signal.id);
        audit.push({ stage: 'signal_ignored', detail: `${signal.id}: unknown direction` });
        continue;
      }

      const summary = summaries.get(assumption.id);
      if (!summary) throw new Error(`Missing signal summary for ${assumption.id}.`);
      if (signal.direction === 'CONTRADICTS') {
        summary.strongestContradiction = Math.max(summary.strongestContradiction, signal.strength);
      } else {
        summary.strongestConfirmation = Math.max(summary.strongestConfirmation, signal.strength);
      }
      audit.push({
        stage: 'signal_accepted',
        detail: `${signal.id}: ${signal.direction.toLowerCase()} ${assumption.id} at strength ${signal.strength}`,
      });
    }

    const totalWeight = contract.assumptions.reduce((sum, assumption) => sum + assumption.weight, 0);
    let weightedContradiction = 0;
    let criticalBreak = false;
    const brokenAssumptionIds: string[] = [];
    const confirmedAssumptionIds: string[] = [];
    const reasons: string[] = [];

    for (const assumption of contract.assumptions) {
      const summary = summaries.get(assumption.id);
      if (!summary) continue;

      weightedContradiction += assumption.weight * (summary.strongestContradiction / 100);

      if (summary.strongestContradiction >= this.config.brokenAssumptionThreshold) {
        brokenAssumptionIds.push(assumption.id);
        reasons.push(`${assumption.id} contradicted at strength ${summary.strongestContradiction}.`);
      }
      if (summary.strongestConfirmation >= this.config.brokenAssumptionThreshold) {
        confirmedAssumptionIds.push(assumption.id);
      }
      if (
        assumption.critical === true
        && summary.strongestContradiction >= this.config.criticalAssumptionThreshold
      ) {
        criticalBreak = true;
        reasons.push(`Critical assumption ${assumption.id} is strongly contradicted.`);
      }
    }

    const driftScore = Math.min(100, Math.round((weightedContradiction / totalWeight) * 100));
    let state: RealityDriftState = 'STABLE';
    if (criticalBreak || driftScore >= this.config.criticalThreshold) state = 'CRITICAL';
    else if (driftScore >= this.config.driftThreshold) state = 'DRIFT';
    else if (driftScore >= this.config.watchThreshold) state = 'WATCH';

    if (reasons.length === 0) reasons.push('No verified contradiction crossed the configured break threshold.');

    const reanalyze = state === 'DRIFT' || state === 'CRITICAL';
    audit.push({ stage: 'drift_score', detail: `score=${driftScore}; state=${state}; reanalyze=${reanalyze}` });

    return {
      contractId: contract.id,
      contractHash: predictionContractHash(contract),
      driftScore,
      state,
      reanalyze,
      brokenAssumptionIds: brokenAssumptionIds.sort(),
      confirmedAssumptionIds: confirmedAssumptionIds.sort(),
      ignoredSignalIds: ignoredSignalIds.sort(),
      reasons,
      audit,
    };
  }
}
