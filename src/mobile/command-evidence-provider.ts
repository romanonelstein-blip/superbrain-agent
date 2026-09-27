import { execa } from 'execa';
import type {
  NexusDissentInput,
  NexusEvidenceInput,
  NexusStance,
} from '../core/nexus.js';
import type {
  MissionAuditItem,
  MissionDraft,
  MissionExecutionInput,
} from './mission-control.js';
import type {
  MissionEvidenceBundle,
  MissionEvidenceProvider,
  MissionEvidenceProviderStatus,
} from './nexus-mission-executor.js';

export interface CommandMissionEvidenceProviderConfig {
  command: string;
  args?: string[];
  providerName?: string;
  timeoutMs?: number;
  maxOutputBytes?: number;
}

interface ProviderRequest {
  protocolVersion: 1;
  type: 'status' | 'collect';
  runId?: string;
  question?: string;
  mode?: string;
}

type JsonObject = Record<string, unknown>;

export class CommandMissionEvidenceProvider implements MissionEvidenceProvider {
  private readonly command: string;
  private readonly args: string[];
  private readonly providerName: string;
  private readonly timeoutMs: number;
  private readonly maxOutputBytes: number;

  constructor(config: CommandMissionEvidenceProviderConfig) {
    const command = config.command.trim();
    if (!command) throw new Error('Evidence provider command must be non-empty.');
    this.command = command;
    this.args = config.args ?? [];
    this.providerName = config.providerName?.trim() || 'command-evidence-provider';
    this.timeoutMs = config.timeoutMs ?? 60_000;
    this.maxOutputBytes = config.maxOutputBytes ?? 1024 * 1024;
    if (!Number.isInteger(this.timeoutMs) || this.timeoutMs < 100 || this.timeoutMs > 10 * 60_000) {
      throw new Error('Evidence provider timeout must be between 100 ms and 10 minutes.');
    }
    if (!Number.isInteger(this.maxOutputBytes) || this.maxOutputBytes < 1024 || this.maxOutputBytes > 10 * 1024 * 1024) {
      throw new Error('Evidence provider maxOutputBytes must be between 1 KiB and 10 MiB.');
    }
  }

  async getStatus(): Promise<MissionEvidenceProviderStatus> {
    try {
      const raw = await this.invoke({
        protocolVersion: 1,
        type: 'status',
      });
      const ready = raw.ready === true;
      if (!ready) {
        return {
          interactiveMissionsAvailable: false,
          researchMissionsAvailable: false,
          configuredProviders: [],
        };
      }
      const configuredProviders = this.stringArray(raw.configuredProviders, 'configuredProviders', 50, 200);
      return {
        interactiveMissionsAvailable: raw.interactiveMissionsAvailable === true,
        researchMissionsAvailable: raw.researchMissionsAvailable === true,
        configuredProviders: configuredProviders.length > 0 ? configuredProviders : [this.providerName],
      };
    } catch {
      return {
        interactiveMissionsAvailable: false,
        researchMissionsAvailable: false,
        configuredProviders: [],
      };
    }
  }

  async collect(input: MissionExecutionInput): Promise<MissionEvidenceBundle> {
    const raw = await this.invoke({
      protocolVersion: 1,
      type: 'collect',
      runId: input.runId,
      question: input.question,
      mode: input.mode,
    });

    const evidence = this.evidenceArray(raw.evidence, 'evidence');
    if (evidence.length === 0) throw new Error('Evidence provider returned no evidence.');

    const dissent = raw.dissent === undefined ? undefined : this.dissent(raw.dissent);
    const draftResponses = raw.draftResponses === undefined
      ? undefined
      : this.drafts(raw.draftResponses);
    const audit = raw.audit === undefined ? undefined : this.audit(raw.audit);
    const verificationNote = raw.verificationNote === undefined
      ? undefined
      : this.optionalString(raw.verificationNote, 'verificationNote', 20_000);

    return {
      evidence,
      ...(dissent ? { dissent } : {}),
      ...(draftResponses ? { draftResponses } : {}),
      ...(audit ? { audit } : {}),
      ...(verificationNote ? { verificationNote } : {}),
    };
  }

  private async invoke(payload: ProviderRequest): Promise<JsonObject> {
    const { stdout } = await execa(this.command, this.args, {
      input: JSON.stringify(payload),
      timeout: this.timeoutMs,
      reject: true,
      maxBuffer: this.maxOutputBytes,
      shell: false,
      env: {
        ...process.env,
        SUPERBRAIN_EVIDENCE_PROTOCOL: '1',
      },
    });
    const text = stdout.trim();
    if (!text) throw new Error('Evidence provider returned empty stdout.');
    let parsed: unknown;
    try {
      parsed = JSON.parse(text) as unknown;
    } catch {
      throw new Error('Evidence provider stdout must contain exactly one JSON object.');
    }
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new Error('Evidence provider stdout must be a JSON object.');
    }
    const object = parsed as JsonObject;
    if (object.protocolVersion !== undefined && object.protocolVersion !== 1) {
      throw new Error('Unsupported evidence provider protocol version.');
    }
    return object;
  }

  private evidenceArray(value: unknown, field: string): NexusEvidenceInput[] {
    if (!Array.isArray(value)) throw new Error(`${field} must be an array.`);
    if (value.length > 500) throw new Error(`${field} exceeds the maximum of 500 items.`);
    return value.map((item, index): NexusEvidenceInput => this.evidence(item, `${field}[${index}]`));
  }

  private evidence(value: unknown, field: string): NexusEvidenceInput {
    const object = this.object(value, field);
    const id = this.requiredString(object.id, `${field}.id`, 500);
    const claim = this.requiredString(object.claim, `${field}.claim`, 50_000);
    const sourceId = this.requiredString(object.sourceId, `${field}.sourceId`, 4_000);
    const sourceFamily = this.requiredString(object.sourceFamily, `${field}.sourceFamily`, 500);
    const verified = object.verified === true;
    const citation = object.citation === undefined
      ? undefined
      : this.optionalString(object.citation, `${field}.citation`, 8_000);
    const contentHash = object.contentHash === undefined
      ? undefined
      : this.optionalString(object.contentHash, `${field}.contentHash`, 1_000);
    if (verified && (!citation || !contentHash)) {
      throw new Error(`${field}: verified evidence requires citation and contentHash.`);
    }

    const stance = object.stance === undefined ? undefined : this.stance(object.stance, `${field}.stance`);
    const reliability = this.optionalScore(object.reliability, `${field}.reliability`);
    const freshness = this.optionalScore(object.freshness, `${field}.freshness`);
    const relevance = this.optionalScore(object.relevance, `${field}.relevance`);
    const retrievedAt = object.retrievedAt === undefined
      ? undefined
      : this.optionalString(object.retrievedAt, `${field}.retrievedAt`, 200);
    const location = object.location === undefined
      ? undefined
      : this.optionalString(object.location, `${field}.location`, 2_000);
    const contentType = object.contentType === undefined
      ? undefined
      : this.optionalString(object.contentType, `${field}.contentType`, 500);
    const provider = object.provider === undefined
      ? undefined
      : this.optionalString(object.provider, `${field}.provider`, 500);
    const providerModel = object.providerModel === undefined
      ? undefined
      : this.optionalString(object.providerModel, `${field}.providerModel`, 500);
    const providerRequestId = object.providerRequestId === undefined
      ? undefined
      : this.optionalString(object.providerRequestId, `${field}.providerRequestId`, 2_000);
    const providerAgent = object.providerAgent === undefined
      ? undefined
      : this.optionalString(object.providerAgent, `${field}.providerAgent`, 500);
    const providerAttempts = this.optionalInteger(object.providerAttempts, `${field}.providerAttempts`, 0, 100);
    const providerLatencyMs = this.optionalInteger(object.providerLatencyMs, `${field}.providerLatencyMs`, 0, 60 * 60 * 1000);

    return {
      id,
      claim,
      sourceId,
      sourceFamily,
      ...(stance ? { stance } : {}),
      ...(reliability !== undefined ? { reliability } : {}),
      ...(freshness !== undefined ? { freshness } : {}),
      ...(relevance !== undefined ? { relevance } : {}),
      ...(verified ? { verified: true } : {}),
      ...(citation ? { citation } : {}),
      ...(contentHash ? { contentHash } : {}),
      ...(retrievedAt ? { retrievedAt } : {}),
      ...(location ? { location } : {}),
      ...(contentType ? { contentType } : {}),
      ...(provider ? { provider } : {}),
      ...(providerModel ? { providerModel } : {}),
      ...(providerRequestId ? { providerRequestId } : {}),
      ...(providerAgent ? { providerAgent } : {}),
      ...(providerAttempts !== undefined ? { providerAttempts } : {}),
      ...(providerLatencyMs !== undefined ? { providerLatencyMs } : {}),
    };
  }

  private dissent(value: unknown): NexusDissentInput {
    const object = this.object(value, 'dissent');
    if (object.completed !== true) throw new Error('dissent.completed must be true.');
    const provider = this.requiredString(object.provider, 'dissent.provider', 500);
    const requestId = object.requestId === undefined
      ? undefined
      : this.optionalString(object.requestId, 'dissent.requestId', 2_000);
    const evidence = this.evidenceArray(object.evidence, 'dissent.evidence');
    return {
      completed: true,
      provider,
      ...(requestId ? { requestId } : {}),
      evidence,
    };
  }

  private drafts(value: unknown): MissionDraft[] {
    if (!Array.isArray(value)) throw new Error('draftResponses must be an array.');
    if (value.length > 100) throw new Error('draftResponses exceeds the maximum of 100 items.');
    return value.map((item, index): MissionDraft => {
      const object = this.object(item, `draftResponses[${index}]`);
      const agent = object.agent === undefined
        ? undefined
        : this.optionalString(object.agent, `draftResponses[${index}].agent`, 500);
      const text = object.text === undefined
        ? undefined
        : this.optionalString(object.text, `draftResponses[${index}].text`, 100_000);
      const verified = object.verified === undefined
        ? undefined
        : this.boolean(object.verified, `draftResponses[${index}].verified`);
      return {
        ...(agent ? { agent } : {}),
        ...(text ? { text } : {}),
        ...(verified !== undefined ? { verified } : {}),
      };
    });
  }

  private audit(value: unknown): MissionAuditItem[] {
    if (!Array.isArray(value)) throw new Error('audit must be an array.');
    if (value.length > 500) throw new Error('audit exceeds the maximum of 500 items.');
    return value.map((item, index): MissionAuditItem => {
      const object = this.object(item, `audit[${index}]`);
      return {
        stage: this.requiredString(object.stage, `audit[${index}].stage`, 500),
        detail: this.requiredString(object.detail, `audit[${index}].detail`, 20_000),
      };
    });
  }

  private object(value: unknown, field: string): JsonObject {
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
      throw new Error(`${field} must be an object.`);
    }
    return value as JsonObject;
  }

  private requiredString(value: unknown, field: string, maxLength: number): string {
    const parsed = this.optionalString(value, field, maxLength);
    if (!parsed) throw new Error(`${field} must be a non-empty string.`);
    return parsed;
  }

  private optionalString(value: unknown, field: string, maxLength: number): string {
    if (typeof value !== 'string') throw new Error(`${field} must be a string.`);
    const parsed = value.trim();
    if (parsed.length > maxLength) throw new Error(`${field} exceeds ${maxLength} characters.`);
    return parsed;
  }

  private boolean(value: unknown, field: string): boolean {
    if (typeof value !== 'boolean') throw new Error(`${field} must be boolean.`);
    return value;
  }

  private stance(value: unknown, field: string): NexusStance {
    if (value === 'support' || value === 'challenge' || value === 'neutral') return value;
    throw new Error(`${field} must be support, challenge or neutral.`);
  }

  private optionalScore(value: unknown, field: string): number | undefined {
    if (value === undefined) return undefined;
    if (typeof value !== 'number' || !Number.isFinite(value) || value < 0 || value > 1) {
      throw new Error(`${field} must be a number between 0 and 1.`);
    }
    return value;
  }

  private optionalInteger(
    value: unknown,
    field: string,
    minimum: number,
    maximum: number,
  ): number | undefined {
    if (value === undefined) return undefined;
    if (!Number.isInteger(value) || typeof value !== 'number' || value < minimum || value > maximum) {
      throw new Error(`${field} must be an integer between ${minimum} and ${maximum}.`);
    }
    return value;
  }

  private stringArray(value: unknown, field: string, maxItems: number, maxLength: number): string[] {
    if (value === undefined) return [];
    if (!Array.isArray(value)) throw new Error(`${field} must be an array.`);
    if (value.length > maxItems) throw new Error(`${field} exceeds ${maxItems} items.`);
    return value.map((item, index): string => this.requiredString(item, `${field}[${index}]`, maxLength));
  }
}
