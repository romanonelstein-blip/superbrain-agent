import {
  CrmDataGateway,
  type CrmDataProvider,
  type CrmDataResult,
  type CrmProviderStatus,
} from '../crm/data-gateway';
import {
  type JsonHttpRequest,
  type JsonHttpResponse,
  type JsonHttpTransport,
} from '../crm/http-json-transport';
import { ApolloDataProvider } from '../crm/providers/apollo-provider';
import { HunterDataProvider } from '../crm/providers/hunter-provider';

class FakeProvider implements CrmDataProvider {
  readonly capabilities = ['EMAIL_VERIFY'] as const;

  constructor(
    readonly id: string,
    readonly profile: { quality: number; costEfficiency: number; speed: number },
    private readonly result: CrmDataResult,
    private readonly status: CrmProviderStatus = { available: true },
    private readonly shouldThrow = false,
  ) {}

  async getStatus(): Promise<CrmProviderStatus> {
    return this.status;
  }

  async execute(): Promise<CrmDataResult> {
    if (this.shouldThrow) throw new Error('credential-bearing upstream failure');
    return this.result;
  }
}

class RecordingTransport implements JsonHttpTransport {
  lastRequest: JsonHttpRequest | null = null;

  constructor(private readonly response: JsonHttpResponse) {}

  async request(input: JsonHttpRequest): Promise<JsonHttpResponse> {
    this.lastRequest = input;
    return this.response;
  }
}

function result(providerId: string, outcome: 'FOUND' | 'NOT_FOUND'): CrmDataResult {
  return {
    providerId,
    capability: 'EMAIL_VERIFY',
    outcome,
    confidence: outcome === 'FOUND' ? 90 : 0,
    data: outcome === 'FOUND' ? { status: 'valid' } : {},
    evidence: [{ source: providerId, retrievedAt: '2026-09-28T16:00:00.000Z' }],
  };
}

describe('CrmDataGateway', (): void => {
  test('selects the strongest provider profile first', async (): Promise<void> => {
    const lower = new FakeProvider('lower', { quality: 50, costEfficiency: 50, speed: 50 }, result('lower', 'FOUND'));
    const higher = new FakeProvider('higher', { quality: 95, costEfficiency: 90, speed: 90 }, result('higher', 'FOUND'));
    const gateway = new CrmDataGateway([lower, higher]);

    const response = await gateway.resolve({ capability: 'EMAIL_VERIFY', input: { email: 'test@example.com' } });

    expect(response.result?.providerId).toBe('higher');
    expect(response.attempts).toEqual([{ providerId: 'higher', state: 'FOUND' }]);
  });

  test('falls back when the first provider errors or has no match', async (): Promise<void> => {
    const broken = new FakeProvider(
      'broken',
      { quality: 100, costEfficiency: 100, speed: 100 },
      result('broken', 'NOT_FOUND'),
      { available: true },
      true,
    );
    const empty = new FakeProvider('empty', { quality: 90, costEfficiency: 90, speed: 90 }, result('empty', 'NOT_FOUND'));
    const fallback = new FakeProvider('fallback', { quality: 80, costEfficiency: 80, speed: 80 }, result('fallback', 'FOUND'));
    const gateway = new CrmDataGateway([broken, empty, fallback]);

    const response = await gateway.resolve({ capability: 'EMAIL_VERIFY', input: { email: 'test@example.com' } });

    expect(response.result?.providerId).toBe('fallback');
    expect(response.attempts).toEqual([
      { providerId: 'broken', state: 'ERROR' },
      { providerId: 'empty', state: 'NOT_FOUND' },
      { providerId: 'fallback', state: 'FOUND' },
    ]);
  });

  test('honors explicit provider preference without changing provider contracts', async (): Promise<void> => {
    const first = new FakeProvider('first', { quality: 95, costEfficiency: 95, speed: 95 }, result('first', 'FOUND'));
    const preferred = new FakeProvider('preferred', { quality: 60, costEfficiency: 60, speed: 60 }, result('preferred', 'FOUND'));
    const gateway = new CrmDataGateway([first, preferred]);

    const response = await gateway.resolve({
      capability: 'EMAIL_VERIFY',
      input: { email: 'test@example.com' },
      preferredProviders: ['preferred'],
    });

    expect(response.result?.providerId).toBe('preferred');
  });
});

describe('ApolloDataProvider', (): void => {
  test('uses header authentication and maps people enrichment', async (): Promise<void> => {
    const transport = new RecordingTransport({
      status: 200,
      body: { match_confidence: 'high', person: { id: 'person-1', name: 'Test Person' } },
    });
    const provider = new ApolloDataProvider({ apiKey: 'apollo-secret', transport });

    const response = await provider.execute({
      capability: 'PERSON_ENRICHMENT',
      input: { email: 'person@example.com' },
    });

    expect(response.outcome).toBe('FOUND');
    expect(response.confidence).toBe(95);
    expect(transport.lastRequest?.headers?.['x-api-key']).toBe('apollo-secret');
    expect(transport.lastRequest?.url).not.toContain('apollo-secret');
    expect(transport.lastRequest?.query).not.toHaveProperty('api_key');
  });
});

describe('HunterDataProvider', (): void => {
  test('keeps the API key out of the URL while verifying email', async (): Promise<void> => {
    const transport = new RecordingTransport({ status: 200, body: { data: { status: 'valid', score: 99 } } });
    const provider = new HunterDataProvider({ apiKey: 'hunter-secret', transport });

    const response = await provider.execute({ capability: 'EMAIL_VERIFY', input: { email: 'person@example.com' } });

    expect(response.outcome).toBe('FOUND');
    expect(response.confidence).toBe(99);
    expect(transport.lastRequest?.headers?.['x-api-key']).toBe('hunter-secret');
    expect(transport.lastRequest?.url).not.toContain('hunter-secret');
    expect(transport.lastRequest?.query).not.toHaveProperty('api_key');
  });
});


class CountingProvider implements CrmDataProvider {
  readonly capabilities = ['EMAIL_VERIFY'] as const;
  executions = 0;

  constructor(
    readonly id: string,
    readonly profile: { quality: number; costEfficiency: number; speed: number },
    private readonly providerResult: CrmDataResult,
    private readonly status: CrmProviderStatus = { available: true },
  ) {}

  async getStatus(): Promise<CrmProviderStatus> {
    return this.status;
  }

  async execute(): Promise<CrmDataResult> {
    this.executions += 1;
    return this.providerResult;
  }
}

describe('CrmDataGateway provider execution policy', (): void => {
  test('sanitizes failed availability checks and keeps the budget for a usable fallback', async (): Promise<void> => {
    const unavailable = new CountingProvider(
      'unavailable', { quality: 100, costEfficiency: 100, speed: 100 }, result('unavailable', 'FOUND'),
    );
    unavailable.getStatus = async (): Promise<CrmProviderStatus> => {
      throw new Error('private provider credentials and account data');
    };
    const fallback = new CountingProvider(
      'fallback', { quality: 90, costEfficiency: 90, speed: 90 }, result('fallback', 'FOUND'),
    );
    const response = await new CrmDataGateway([unavailable, fallback]).resolve({
      capability: 'EMAIL_VERIFY', input: {}, maxProviderAttempts: 1,
    });
    expect(response.attempts).toEqual([
      { providerId: 'unavailable', state: 'UNAVAILABLE' },
      { providerId: 'fallback', state: 'FOUND' },
    ]);
    expect(response.result?.providerId).toBe('fallback');
    expect(unavailable.executions).toBe(0);
    expect(fallback.executions).toBe(1);
    expect(JSON.stringify(response)).not.toContain('private');
  });

  test('executes only providers explicitly allowed by policy', async (): Promise<void> => {
    const blocked = new CountingProvider(
      'blocked',
      { quality: 100, costEfficiency: 100, speed: 100 },
      result('blocked', 'FOUND'),
    );
    const allowed = new CountingProvider(
      'allowed',
      { quality: 50, costEfficiency: 50, speed: 50 },
      result('allowed', 'FOUND'),
    );
    const gateway = new CrmDataGateway([blocked, allowed]);

    const response = await gateway.resolve({
      capability: 'EMAIL_VERIFY',
      input: { email: 'test@example.com' },
      allowedProviders: ['allowed'],
    });

    expect(response.result?.providerId).toBe('allowed');
    expect(blocked.executions).toBe(0);
    expect(allowed.executions).toBe(1);
  });

  test('fails closed when the allowlist permits no provider', async (): Promise<void> => {
    const provider = new CountingProvider(
      'provider',
      { quality: 80, costEfficiency: 80, speed: 80 },
      result('provider', 'FOUND'),
    );
    const gateway = new CrmDataGateway([provider]);

    const response = await gateway.resolve({
      capability: 'EMAIL_VERIFY',
      input: { email: 'test@example.com' },
      allowedProviders: [],
    });

    expect(response).toEqual({
      result: null,
      attempts: [],
      stoppedReason: 'NO_ALLOWED_PROVIDER',
    });
    expect(provider.executions).toBe(0);
  });

  test('caps paid provider executions before fallback can continue', async (): Promise<void> => {
    const first = new CountingProvider(
      'first',
      { quality: 100, costEfficiency: 100, speed: 100 },
      result('first', 'NOT_FOUND'),
    );
    const fallback = new CountingProvider(
      'fallback',
      { quality: 90, costEfficiency: 90, speed: 90 },
      result('fallback', 'FOUND'),
    );
    const gateway = new CrmDataGateway([first, fallback]);

    const response = await gateway.resolve({
      capability: 'EMAIL_VERIFY',
      input: { email: 'test@example.com' },
      maxProviderAttempts: 1,
    });

    expect(response.result).toBeNull();
    expect(response.stoppedReason).toBe('MAX_PROVIDER_ATTEMPTS');
    expect(response.attempts).toEqual([
      { providerId: 'first', state: 'NOT_FOUND' },
    ]);
    expect(first.executions).toBe(1);
    expect(fallback.executions).toBe(0);
  });

  test('an unavailable provider does not consume the execution budget', async (): Promise<void> => {
    const unavailable = new CountingProvider(
      'unavailable',
      { quality: 100, costEfficiency: 100, speed: 100 },
      result('unavailable', 'FOUND'),
      { available: false, reason: 'disabled' },
    );
    const fallback = new CountingProvider(
      'fallback',
      { quality: 90, costEfficiency: 90, speed: 90 },
      result('fallback', 'FOUND'),
    );
    const gateway = new CrmDataGateway([unavailable, fallback]);

    const response = await gateway.resolve({
      capability: 'EMAIL_VERIFY',
      input: { email: 'test@example.com' },
      maxProviderAttempts: 1,
    });

    expect(response.result?.providerId).toBe('fallback');
    expect(response.attempts).toEqual([
      { providerId: 'unavailable', state: 'UNAVAILABLE' },
      { providerId: 'fallback', state: 'FOUND' },
    ]);
    expect(unavailable.executions).toBe(0);
    expect(fallback.executions).toBe(1);
  });

  test('rejects an invalid provider attempt budget', async (): Promise<void> => {
    const provider = new CountingProvider(
      'provider',
      { quality: 80, costEfficiency: 80, speed: 80 },
      result('provider', 'FOUND'),
    );
    const gateway = new CrmDataGateway([provider]);

    await expect(gateway.resolve({
      capability: 'EMAIL_VERIFY',
      input: { email: 'test@example.com' },
      maxProviderAttempts: 0,
    })).rejects.toThrow('maxProviderAttempts must be a positive integer');
  });
});
