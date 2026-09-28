import type {
  CrmDataCapability,
  CrmDataProvider,
  CrmDataRequest,
  CrmDataResult,
  CrmProviderProfile,
  CrmProviderStatus,
} from '../data-gateway.js';
import {
  FetchJsonHttpTransport,
  type JsonHttpResponse,
  type JsonHttpTransport,
} from '../http-json-transport.js';

const CLAY_API_BASE = 'https://api.clay.com/public/v0';

export interface ClayDataProviderConfig {
  apiKey: string;
  personEnrichmentRoutineId?: string;
  companyEnrichmentRoutineId?: string;
  transport?: JsonHttpTransport;
  timeoutMs?: number;
  pollIntervalMs?: number;
  maxPollAttempts?: number;
  sleep?: (ms: number) => Promise<void>;
  personResultKey?: string;
  companyResultKey?: string;
}

const PROFILE: CrmProviderProfile = {
  quality: 92,
  costEfficiency: 55,
  speed: 60,
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function nonEmptyString(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim().length > 0
    ? value.trim()
    : undefined;
}

function routineRunId(body: unknown): string | undefined {
  if (!isRecord(body)) return undefined;
  return nonEmptyString(body.routine_run_id) ?? nonEmptyString(body.routineRunId);
}

function firstRoutineResult(body: unknown): Record<string, unknown> | null {
  if (!isRecord(body) || !Array.isArray(body.data) || body.data.length === 0) return null;
  const item = body.data[0];
  if (!isRecord(item) || !isRecord(item.result)) return null;
  return item.result;
}

function complete(body: unknown): boolean {
  return isRecord(body) && body.status === 'complete';
}

function failed(body: unknown): boolean {
  if (!isRecord(body)) return false;
  return body.status === 'failed' || body.status === 'error' || body.status === 'cancelled';
}

function defaultSleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

export class ClayDataProvider implements CrmDataProvider {
  readonly id = 'clay';
  readonly profile = PROFILE;
  readonly capabilities: readonly CrmDataCapability[];

  private readonly apiKey: string;
  private readonly personRoutineId?: string;
  private readonly companyRoutineId?: string;
  private readonly transport: JsonHttpTransport;
  private readonly timeoutMs: number;
  private readonly pollIntervalMs: number;
  private readonly maxPollAttempts: number;
  private readonly sleep: (ms: number) => Promise<void>;
  private readonly personResultKey: string;
  private readonly companyResultKey: string;

  constructor(config: ClayDataProviderConfig) {
    this.apiKey = config.apiKey.trim();
    this.personRoutineId = nonEmptyString(config.personEnrichmentRoutineId);
    this.companyRoutineId = nonEmptyString(config.companyEnrichmentRoutineId);
    this.transport = config.transport ?? new FetchJsonHttpTransport();
    this.timeoutMs = config.timeoutMs ?? 8_000;
    this.pollIntervalMs = config.pollIntervalMs ?? 5_000;
    this.maxPollAttempts = config.maxPollAttempts ?? 15;
    this.sleep = config.sleep ?? defaultSleep;
    this.personResultKey = config.personResultKey ?? 'Enrich person';
    this.companyResultKey = config.companyResultKey ?? 'Enrich Company';

    const capabilities: CrmDataCapability[] = [];
    if (this.personRoutineId) capabilities.push('PERSON_ENRICHMENT');
    if (this.companyRoutineId) capabilities.push('COMPANY_ENRICHMENT');
    this.capabilities = capabilities;
  }

  async getStatus(): Promise<CrmProviderStatus> {
    if (this.apiKey.length === 0) {
      return { available: false, reason: 'missing_api_key' };
    }
    if (this.capabilities.length === 0) {
      return { available: false, reason: 'missing_routine_ids' };
    }
    return { available: true };
  }

  async execute(request: CrmDataRequest): Promise<CrmDataResult> {
    if (!this.capabilities.includes(request.capability)) {
      throw new Error(`Clay does not support ${request.capability} with the configured routines`);
    }
    if (this.apiKey.length === 0) {
      throw new Error('Clay API key is not configured');
    }

    const { routineId, inputs, resultKey } = this.mapRequest(request);
    const start = await this.transport.request({
      method: 'POST',
      url: `${CLAY_API_BASE}/routines/${encodeURIComponent(routineId)}/run`,
      headers: { 'clay-api-key': this.apiKey },
      body: {
        items: [
          {
            id: 'superbrain-item',
            inputs,
          },
        ],
      },
      timeoutMs: this.timeoutMs,
    });

    this.assertSuccessful(start, 'routine start');
    const runId = routineRunId(start.body);
    if (!runId) throw new Error('Clay routine start did not return a run id');

    const result = await this.pollForResult(runId, resultKey);

    return {
      providerId: this.id,
      capability: request.capability,
      outcome: result ? 'FOUND' : 'NOT_FOUND',
      confidence: result ? 80 : 0,
      data: result ?? {},
      evidence: [
        {
          source: this.id,
          retrievedAt: new Date().toISOString(),
          externalId: runId,
        },
      ],
    };
  }

  private mapRequest(request: CrmDataRequest): {
    routineId: string;
    inputs: Readonly<Record<string, unknown>>;
    resultKey: string;
  } {
    if (request.capability === 'PERSON_ENRICHMENT') {
      if (!this.personRoutineId) throw new Error('Clay person enrichment routine is not configured');

      const email = nonEmptyString(request.input.email);
      const professionalProfileUrl = nonEmptyString(request.input.linkedinUrl)
        ?? nonEmptyString(request.input.professionalProfileUrl);

      if (!email && !professionalProfileUrl) {
        throw new Error('Clay person enrichment requires email or professional profile URL');
      }

      return {
        routineId: this.personRoutineId,
        inputs: {
          ...(email ? { Email: email } : {}),
          ...(professionalProfileUrl ? { 'Professional Profile URL': professionalProfileUrl } : {}),
        },
        resultKey: this.personResultKey,
      };
    }

    if (request.capability === 'COMPANY_ENRICHMENT') {
      if (!this.companyRoutineId) throw new Error('Clay company enrichment routine is not configured');
      const identifier = nonEmptyString(request.input.domain)
        ?? nonEmptyString(request.input.linkedinUrl)
        ?? nonEmptyString(request.input.companyIdentifier);

      if (!identifier) {
        throw new Error('Clay company enrichment requires a company identifier');
      }

      return {
        routineId: this.companyRoutineId,
        inputs: { 'Company Identifier': identifier },
        resultKey: this.companyResultKey,
      };
    }

    throw new Error(`Clay does not support ${request.capability}`);
  }

  private async pollForResult(
    runId: string,
    resultKey: string,
  ): Promise<Record<string, unknown> | null> {
    for (let attempt = 0; attempt < this.maxPollAttempts; attempt += 1) {
      const response = await this.transport.request({
        method: 'GET',
        url: `${CLAY_API_BASE}/routines/run/${encodeURIComponent(runId)}/results`,
        headers: { 'clay-api-key': this.apiKey },
        timeoutMs: this.timeoutMs,
      });

      this.assertSuccessful(response, 'routine results');

      if (failed(response.body)) {
        throw new Error('Clay routine failed');
      }

      if (complete(response.body)) {
        const routineResult = firstRoutineResult(response.body);
        if (!routineResult) return null;
        const value = routineResult[resultKey];
        return isRecord(value) && Object.keys(value).length > 0 ? value : null;
      }

      if (attempt + 1 < this.maxPollAttempts) {
        await this.sleep(this.pollIntervalMs);
      }
    }

    throw new Error('Clay routine did not complete within the configured polling window');
  }

  private assertSuccessful(response: JsonHttpResponse, operation: string): void {
    if (response.status === 401 || response.status === 403) {
      throw new Error('Clay authentication failed');
    }
    if (response.status === 429) {
      throw new Error('Clay rate limit reached');
    }
    if (response.status < 200 || response.status >= 300) {
      throw new Error(`Clay ${operation} failed`);
    }
  }
}
