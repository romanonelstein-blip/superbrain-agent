import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { dirname } from 'node:path';
import {
  RealitySentinel,
  predictionContractHash,
  type PredictionAssumption,
  type PredictionContract,
  type RealitySentinelAssessment,
  type RealitySignal,
  type RealitySignalDirection,
} from '../core/reality-sentinel.js';

export interface RealityEvidenceReference {
  id: string;
  verified: boolean;
}

export interface RealitySignalInput {
  id: string;
  assumptionId: string;
  direction: RealitySignalDirection;
  strength: number;
  evidenceId?: string;
  observedAt?: string;
}

export interface RealityAssessmentRecord {
  runId: string;
  createdAt: string;
  assessment: RealitySentinelAssessment;
}

export interface StoredPredictionContract {
  contract: PredictionContract;
  contractHash: string;
  sourceRunId?: string;
  assessments: RealityAssessmentRecord[];
}

export interface PredictionContractSummary {
  id: string;
  decision: string;
  createdAt: string;
  contractHash: string;
  sourceRunId?: string;
  assessmentCount: number;
  latestState?: RealitySentinelAssessment['state'];
  latestDriftScore?: number;
}

interface RealityDatabase {
  version: 1;
  contracts: StoredPredictionContract[];
}

export class RealitySentinelControlError extends Error {
  readonly statusCode: number;

  constructor(statusCode: number, message: string) {
    super(message);
    this.statusCode = statusCode;
  }
}

function record(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new RealitySentinelControlError(400, `${label} must be an object.`);
  }
  return value as Record<string, unknown>;
}

function requiredString(value: unknown, label: string, maxLength = 20_000): string {
  if (typeof value !== 'string' || !value.trim()) {
    throw new RealitySentinelControlError(400, `${label} must be a non-empty string.`);
  }
  const trimmed = value.trim();
  if (trimmed.length > maxLength) {
    throw new RealitySentinelControlError(413, `${label} is too large.`);
  }
  return trimmed;
}

function optionalString(value: unknown, label: string, maxLength = 2_000): string | undefined {
  if (value === undefined) return undefined;
  if (typeof value !== 'string' || !value.trim()) {
    throw new RealitySentinelControlError(400, `${label} must be a non-empty string when provided.`);
  }
  const trimmed = value.trim();
  if (trimmed.length > maxLength) {
    throw new RealitySentinelControlError(413, `${label} is too large.`);
  }
  return trimmed;
}

function parseContract(input: unknown): PredictionContract {
  const value = record(input, 'contract');
  if (!Array.isArray(value.assumptions) || value.assumptions.length === 0) {
    throw new RealitySentinelControlError(400, 'contract.assumptions must be a non-empty array.');
  }
  if (value.assumptions.length > 100) {
    throw new RealitySentinelControlError(413, 'contract.assumptions contains too many entries.');
  }

  const assumptions: PredictionAssumption[] = value.assumptions.map((item, index): PredictionAssumption => {
    const assumption = record(item, `contract.assumptions[${index}]`);
    if (typeof assumption.weight !== 'number') {
      throw new RealitySentinelControlError(400, `contract.assumptions[${index}].weight must be a number.`);
    }
    if (assumption.critical !== undefined && typeof assumption.critical !== 'boolean') {
      throw new RealitySentinelControlError(400, `contract.assumptions[${index}].critical must be a boolean.`);
    }
    return {
      id: requiredString(assumption.id, `contract.assumptions[${index}].id`, 200),
      statement: requiredString(assumption.statement, `contract.assumptions[${index}].statement`, 4_000),
      weight: assumption.weight,
      ...(assumption.critical === true ? { critical: true } : {}),
    };
  });

  const contract: PredictionContract = {
    id: requiredString(value.id, 'contract.id', 200),
    decision: requiredString(value.decision, 'contract.decision', 20_000),
    createdAt: requiredString(value.createdAt, 'contract.createdAt', 200),
    assumptions,
  };

  try {
    predictionContractHash(contract);
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Prediction contract is invalid.';
    throw new RealitySentinelControlError(400, message);
  }
  return contract;
}

function parseSignals(input: unknown): RealitySignalInput[] {
  if (!Array.isArray(input) || input.length === 0) {
    throw new RealitySentinelControlError(400, 'signals must be a non-empty array.');
  }
  if (input.length > 500) throw new RealitySentinelControlError(413, 'signals contains too many entries.');

  return input.map((item, index): RealitySignalInput => {
    const signal = record(item, `signals[${index}]`);
    const direction = requiredString(signal.direction, `signals[${index}].direction`, 20);
    if (!['CONFIRMS', 'CONTRADICTS', 'UNKNOWN'].includes(direction)) {
      throw new RealitySentinelControlError(400, `signals[${index}].direction is invalid.`);
    }
    if (typeof signal.strength !== 'number' || !Number.isInteger(signal.strength) || signal.strength < 0 || signal.strength > 100) {
      throw new RealitySentinelControlError(400, `signals[${index}].strength must be an integer between 0 and 100.`);
    }
    return {
      id: requiredString(signal.id, `signals[${index}].id`, 200),
      assumptionId: requiredString(signal.assumptionId, `signals[${index}].assumptionId`, 200),
      direction: direction as RealitySignalDirection,
      strength: signal.strength,
      ...(optionalString(signal.evidenceId, `signals[${index}].evidenceId`, 200) ? {
        evidenceId: optionalString(signal.evidenceId, `signals[${index}].evidenceId`, 200),
      } : {}),
      ...(optionalString(signal.observedAt, `signals[${index}].observedAt`, 200) ? {
        observedAt: optionalString(signal.observedAt, `signals[${index}].observedAt`, 200),
      } : {}),
    };
  });
}

export class RealitySentinelControl {
  private readonly filePath: string;
  private readonly sentinel: RealitySentinel;
  private loaded = false;
  private readonly records = new Map<string, StoredPredictionContract>();
  private writeQueue: Promise<void> = Promise.resolve();

  constructor(filePath: string, sentinel: RealitySentinel = new RealitySentinel()) {
    this.filePath = filePath;
    this.sentinel = sentinel;
  }

  async list(): Promise<PredictionContractSummary[]> {
    await this.load();
    return Array.from(this.records.values())
      .map((item): PredictionContractSummary => {
        const latest = item.assessments.at(-1)?.assessment;
        return {
          id: item.contract.id,
          decision: item.contract.decision,
          createdAt: item.contract.createdAt,
          contractHash: item.contractHash,
          ...(item.sourceRunId ? { sourceRunId: item.sourceRunId } : {}),
          assessmentCount: item.assessments.length,
          ...(latest ? { latestState: latest.state, latestDriftScore: latest.driftScore } : {}),
        };
      })
      .sort((a, b): number => b.createdAt.localeCompare(a.createdAt));
  }

  async get(contractId: string): Promise<StoredPredictionContract | null> {
    await this.load();
    const item = this.records.get(contractId);
    return item ? structuredClone(item) : null;
  }

  async register(input: unknown, sourceRunId?: string): Promise<StoredPredictionContract> {
    await this.load();
    const contract = parseContract(input);
    if (this.records.has(contract.id)) {
      throw new RealitySentinelControlError(409, 'Prediction contract id already exists and is immutable.');
    }
    const stored: StoredPredictionContract = {
      contract,
      contractHash: predictionContractHash(contract),
      ...(sourceRunId ? { sourceRunId } : {}),
      assessments: [],
    };
    this.records.set(contract.id, structuredClone(stored));
    await this.persist();
    return structuredClone(stored);
  }

  async assess(
    contractId: string,
    runId: string,
    inputSignals: unknown,
    evidence: RealityEvidenceReference[],
  ): Promise<RealityAssessmentRecord> {
    await this.load();
    const stored = this.records.get(contractId);
    if (!stored) throw new RealitySentinelControlError(404, 'Prediction contract was not found.');

    const verifiedEvidence = new Set(evidence.filter((item) => item.verified).map((item) => item.id));
    const signals: RealitySignal[] = parseSignals(inputSignals).map((signal): RealitySignal => ({
      id: signal.id,
      assumptionId: signal.assumptionId,
      direction: signal.direction,
      strength: signal.strength,
      verified: Boolean(signal.evidenceId && verifiedEvidence.has(signal.evidenceId)),
      ...(signal.evidenceId ? { evidenceId: signal.evidenceId } : {}),
      ...(signal.observedAt ? { observedAt: signal.observedAt } : {}),
    }));

    let assessment: RealitySentinelAssessment;
    try {
      assessment = this.sentinel.assess(stored.contract, signals);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Reality Sentinel assessment failed.';
      throw new RealitySentinelControlError(400, message);
    }

    const result: RealityAssessmentRecord = {
      runId,
      createdAt: new Date().toISOString(),
      assessment,
    };
    stored.assessments.push(structuredClone(result));
    await this.persist();
    return structuredClone(result);
  }

  private async load(): Promise<void> {
    if (this.loaded) return;
    this.loaded = true;
    try {
      const raw = await readFile(this.filePath, 'utf8');
      const parsed = JSON.parse(raw) as RealityDatabase;
      if (parsed.version !== 1 || !Array.isArray(parsed.contracts)) return;
      for (const item of parsed.contracts) {
        if (item?.contract?.id) this.records.set(item.contract.id, item);
      }
    } catch (error) {
      const code = (error as NodeJS.ErrnoException).code;
      if (code !== 'ENOENT') throw error;
    }
  }

  private async persist(): Promise<void> {
    const snapshot: RealityDatabase = {
      version: 1,
      contracts: Array.from(this.records.values()),
    };
    const write = async (): Promise<void> => {
      await mkdir(dirname(this.filePath), { recursive: true });
      const temporary = `${this.filePath}.${process.pid}.${Date.now()}.tmp`;
      await writeFile(temporary, JSON.stringify(snapshot, null, 2) + '\n', { encoding: 'utf8', mode: 0o600 });
      await rename(temporary, this.filePath);
    };
    const task = this.writeQueue.then(write, write);
    this.writeQueue = task.catch((): void => undefined);
    await task;
  }
}
