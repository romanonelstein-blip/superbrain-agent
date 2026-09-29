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
  type JsonHttpResponse,
  type JsonHttpTransport,
} from '../http-json-transport.js';

export interface ApolloDataProviderConfig {
  apiKey: string;
  baseUrl?: string;
  transport?: JsonHttpTransport;
  timeoutMs?: number;
}

const CAPABILITIES: readonly CrmDataCapability[] = [
  'PERSON_SEARCH',
  'COMPANY_SEARCH',
  'PERSON_ENRICHMENT',
  'COMPANY_ENRICHMENT',
];

const PROFILE: CrmProviderProfile = {
  quality: 88,
  costEfficiency: 72,
  speed: 82,
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function toQuery(input: CrmDataRequest['input']): Record<string, JsonHttpQueryValue> {
  return { ...input };
}

function confidenceFromApollo(body: Record<string, unknown>, found: boolean): number {
  if (!found) return 0;
  const confidence = body.match_confidence;
  if (confidence === 'high') return 95;
  if (confidence === 'medium') return 75;
  if (confidence === 'low') return 45;
  if (confidence === 'none') return 0;
  return 70;
}

function hasNonEmptyArray(value: unknown): boolean {
  return Array.isArray(value) && value.length > 0;
}

function foundForCapability(capability: CrmDataCapability, body: Record<string, unknown>): boolean {
  switch (capability) {
    case 'PERSON_SEARCH':
      return hasNonEmptyArray(body.people);
    case 'COMPANY_SEARCH':
      return hasNonEmptyArray(body.organizations) || hasNonEmptyArray(body.accounts);
    case 'PERSON_ENRICHMENT':
      return isRecord(body.person);
    case 'COMPANY_ENRICHMENT':
      return isRecord(body.organization);
    default:
      return false;
  }
}

export class ApolloDataProvider implements CrmDataProvider {
  readonly id = 'apollo';
  readonly capabilities = CAPABILITIES;
  readonly profile = PROFILE;

  private readonly apiKey: string;
  private readonly baseUrl: string;
  private readonly transport: JsonHttpTransport;
  private readonly timeoutMs: number;

  constructor(config: ApolloDataProviderConfig) {
    this.apiKey = config.apiKey.trim();
    this.baseUrl = (config.baseUrl ?? 'https://api.apollo.io/api/v1').replace(/\/$/, '');
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
      throw new Error(`Apollo does not support ${request.capability}`);
    }
    if (this.apiKey.length === 0) throw new Error('Apollo API key is not configured');

    const response = await this.callApollo(request);
    if (response.status === 401 || response.status === 403) throw new Error('Apollo authentication failed');
    if (response.status === 429) throw new Error('Apollo rate limit reached');
    if (response.status < 200 || response.status >= 300) throw new Error('Apollo request failed');

    const body = isRecord(response.body) ? response.body : {};
    const found = foundForCapability(request.capability, body);

    return {
      providerId: this.id,
      capability: request.capability,
      outcome: found ? 'FOUND' : 'NOT_FOUND',
      confidence: confidenceFromApollo(body, found),
      data: body,
      evidence: [{ source: this.id, retrievedAt: new Date().toISOString() }],
    };
  }

  private async callApollo(request: CrmDataRequest): Promise<JsonHttpResponse> {
    const query = toQuery(request.input);
    const common = {
      headers: { 'x-api-key': this.apiKey },
      query,
      timeoutMs: this.timeoutMs,
    } as const;

    switch (request.capability) {
      case 'PERSON_SEARCH':
        return this.transport.request({
          method: 'POST',
          url: `${this.baseUrl}/mixed_people/api_search`,
          ...common,
        });
      case 'COMPANY_SEARCH':
        return this.transport.request({
          method: 'POST',
          url: `${this.baseUrl}/mixed_companies/search`,
          ...common,
        });
      case 'PERSON_ENRICHMENT':
        return this.transport.request({
          method: 'POST',
          url: `${this.baseUrl}/people/match`,
          ...common,
        });
      case 'COMPANY_ENRICHMENT':
        return this.transport.request({
          method: 'GET',
          url: `${this.baseUrl}/organizations/enrich`,
          ...common,
        });
      default:
        throw new Error(`Apollo does not support ${request.capability}`);
    }
  }
}
