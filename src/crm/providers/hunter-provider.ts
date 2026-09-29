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
  type JsonHttpQueryValue,
  type JsonHttpTransport,
} from '../http-json-transport.js';

export interface HunterDataProviderConfig {
  apiKey: string;
  baseUrl?: string;
  transport?: JsonHttpTransport;
  timeoutMs?: number;
}

const CAPABILITIES: readonly CrmDataCapability[] = ['EMAIL_FIND', 'EMAIL_VERIFY'];

const PROFILE: CrmProviderProfile = {
  quality: 90,
  costEfficiency: 86,
  speed: 88,
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function toQuery(input: CrmDataRequest['input']): Record<string, JsonHttpQueryValue> {
  return { ...input };
}

function extractData(body: unknown): Record<string, unknown> {
  if (!isRecord(body)) return {};
  return isRecord(body.data) ? body.data : body;
}

function hunterFound(capability: CrmDataCapability, data: Record<string, unknown>): boolean {
  if (capability === 'EMAIL_FIND') {
    return typeof data.email === 'string' && data.email.length > 0;
  }

  if (capability === 'EMAIL_VERIFY') {
    return typeof data.status === 'string' && data.status.length > 0;
  }

  return false;
}

function hunterConfidence(data: Record<string, unknown>, found: boolean): number {
  if (!found) return 0;
  const score = data.score;
  if (typeof score === 'number' && Number.isFinite(score)) {
    return Math.max(0, Math.min(100, score));
  }
  return 70;
}

export class HunterDataProvider implements CrmDataProvider {
  readonly id = 'hunter';
  readonly capabilities = CAPABILITIES;
  readonly profile = PROFILE;

  private readonly apiKey: string;
  private readonly baseUrl: string;
  private readonly transport: JsonHttpTransport;
  private readonly timeoutMs: number;

  constructor(config: HunterDataProviderConfig) {
    this.apiKey = config.apiKey.trim();
    this.baseUrl = (config.baseUrl ?? 'https://api.hunter.io/v2').replace(/\/$/, '');
    this.transport = config.transport ?? new FetchJsonHttpTransport();
    this.timeoutMs = config.timeoutMs ?? 8_000;
  }

  async getStatus(): Promise<CrmProviderStatus> {
    return this.apiKey.length > 0
      ? { available: true }
      : { available: false, reason: 'missing_api_key' };
  }

  async execute(request: CrmDataRequest): Promise<CrmDataResult> {
    if (!this.capabilities.includes(request.capability)) {
      throw new Error(`Hunter does not support ${request.capability}`);
    }
    if (this.apiKey.length === 0) throw new Error('Hunter API key is not configured');

    const endpoint = request.capability === 'EMAIL_FIND' ? 'email-finder' : 'email-verifier';
    const response = await this.transport.request({
      method: 'GET',
      url: `${this.baseUrl}/${endpoint}`,
      headers: { 'x-api-key': this.apiKey },
      query: toQuery(request.input),
      timeoutMs: this.timeoutMs,
    });

    if (response.status === 401 || response.status === 403) throw new Error('Hunter authentication failed');
    if (response.status === 429) throw new Error('Hunter rate limit reached');
    if (response.status < 200 || response.status >= 300) throw new Error('Hunter request failed');

    const data = extractData(response.body);
    const found = hunterFound(request.capability, data);

    return {
      providerId: this.id,
      capability: request.capability,
      outcome: found ? 'FOUND' : 'NOT_FOUND',
      confidence: hunterConfidence(data, found),
      data,
      evidence: [{ source: this.id, retrievedAt: new Date().toISOString() }],
    };
  }
}
