import type {
  CrmDataGatewayResponse,
  CrmDataResult,
  CrmProviderStatus,
  CrmDataRequest,
} from '../crm/data-gateway';
import { CrmDataGateway, type CrmDataProvider } from '../crm/data-gateway';
import {
  NovaProspectsSignalExecutor,
  planNovaProspectsSignal,
  type CrmDataResolver,
  type NovaProspectsSignal,
} from '../crm/novaprospects-signal-planner';

function signal(overrides: Partial<NovaProspectsSignal> = {}): NovaProspectsSignal {
  return {
    signalId: 'signal-1',
    tenantId: 'tenant-a',
    prospectId: 'prospect-1',
    kind: 'PROSPECT_DISCOVERED',
    occurredAt: '2026-09-29T00:00:00.000Z',
    subject: {
      email: 'person@example.com',
      firstName: 'Test',
      lastName: 'Person',
      companyDomain: 'example.com',
    },
    policy: {
      allowExternalEnrichment: true,
      allowEmailDiscovery: true,
    },
    ...overrides,
  };
}

class RecordingResolver implements CrmDataResolver {
  readonly requests: CrmDataRequest[] = [];

  async resolve(request: CrmDataRequest): Promise<CrmDataGatewayResponse> {
    this.requests.push(request);
    return {
      result: null,
      attempts: [],
    };
  }
}

describe('planNovaProspectsSignal', (): void => {
  test('maps a discovered prospect to minimal enrichment capabilities', (): void => {
    const plan = planNovaProspectsSignal(signal());

    expect(plan.requests).toEqual([
      {
        capability: 'COMPANY_ENRICHMENT',
        input: { domain: 'example.com' },
      },
      {
        capability: 'PERSON_ENRICHMENT',
        input: { email: 'person@example.com' },
      },
      {
        capability: 'EMAIL_VERIFY',
        input: { email: 'person@example.com' },
      },
    ]);
  });

  test('discovers an email only when policy explicitly allows it', (): void => {
    const plan = planNovaProspectsSignal(signal({
      subject: {
        firstName: 'Test',
        lastName: 'Person',
        companyDomain: 'example.com',
      },
    }));

    expect(plan.requests).toEqual([
      {
        capability: 'COMPANY_ENRICHMENT',
        input: { domain: 'example.com' },
      },
      {
        capability: 'EMAIL_FIND',
        input: {
          first_name: 'Test',
          last_name: 'Person',
          domain: 'example.com',
        },
      },
    ]);
  });

  test('does not discover an email when policy denies email discovery', (): void => {
    const plan = planNovaProspectsSignal(signal({
      subject: {
        firstName: 'Test',
        lastName: 'Person',
        companyDomain: 'example.com',
      },
      policy: {
        allowExternalEnrichment: true,
        allowEmailDiscovery: false,
      },
    }));

    expect(plan.requests).toEqual([
      {
        capability: 'COMPANY_ENRICHMENT',
        input: { domain: 'example.com' },
      },
    ]);
  });

  test('produces no provider calls when external enrichment is disabled', (): void => {
    const plan = planNovaProspectsSignal(signal({
      policy: {
        allowExternalEnrichment: false,
        allowEmailDiscovery: true,
      },
    }));

    expect(plan.requests).toEqual([]);
  });

  test('keeps tenant and prospect identifiers out of provider input', (): void => {
    const plan = planNovaProspectsSignal(signal());

    for (const request of plan.requests) {
      expect(request.input).not.toHaveProperty('tenantId');
      expect(request.input).not.toHaveProperty('tenant_id');
      expect(request.input).not.toHaveProperty('prospectId');
      expect(request.input).not.toHaveProperty('prospect_id');
    }
  });

  test('limits an email verification signal to email verification', (): void => {
    const plan = planNovaProspectsSignal(signal({
      kind: 'EMAIL_VERIFICATION_REQUIRED',
    }));

    expect(plan.requests).toEqual([
      {
        capability: 'EMAIL_VERIFY',
        input: { email: 'person@example.com' },
      },
    ]);
  });

  test('rejects an empty tenant identifier before any provider work is planned', (): void => {
    expect(() => planNovaProspectsSignal(signal({ tenantId: '   ' })))
      .toThrow('tenantId must not be empty');
  });
});

describe('NovaProspectsSignalExecutor', (): void => {
  test.each(['ERROR', 'NOT_FOUND'] as const)(
    'counts %s fallbacks but not unavailable providers against the shared budget',
    async (outcome): Promise<void> => {
      const executed: string[] = [];
      function provider(id: string, available: boolean): CrmDataProvider {
        return {
          id, capabilities: ['COMPANY_ENRICHMENT', 'PERSON_ENRICHMENT', 'EMAIL_VERIFY'],
          profile: { quality: 100, costEfficiency: 100, speed: 100 },
          async getStatus(): Promise<CrmProviderStatus> { return { available }; },
          async execute(request): Promise<CrmDataResult> {
            executed.push(`${id}:${request.capability}`);
            if (id === 'first' && outcome === 'ERROR') throw new Error('upstream error');
            return {
              providerId: id, capability: request.capability,
              outcome: id === 'first' ? 'NOT_FOUND' : 'FOUND',
              confidence: 1, data: {}, evidence: [],
            };
          },
        };
      }
      const plan = planNovaProspectsSignal(signal({
        policy: {
          allowExternalEnrichment: true, allowEmailDiscovery: true, maxProviderAttempts: 3,
        },
      }));
      const original = JSON.stringify(plan);
      const gateway = new CrmDataGateway([
        provider('offline', false), provider('first', true), provider('fallback', true),
      ]);
      const result = await new NovaProspectsSignalExecutor(gateway).execute(plan);

      expect(executed).toEqual([
        'first:COMPANY_ENRICHMENT', 'fallback:COMPANY_ENRICHMENT', 'first:PERSON_ENRICHMENT',
      ]);
      expect(result.items[1].response.stoppedReason).toBe('MAX_PROVIDER_ATTEMPTS');
      expect(result.items[2].response.attempts).toEqual([]);
      expect(result.items[2].response.stoppedReason).toBe('MAX_PROVIDER_ATTEMPTS');
      expect(JSON.stringify(plan)).toBe(original);
    },
  );

  test.each([0, -1, 1.5, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1])(
    'rejects invalid plan budget %s before contacting the resolver',
    async (maxProviderAttempts): Promise<void> => {
      const resolver = new RecordingResolver();
      const plan = { ...planNovaProspectsSignal(signal()), maxProviderAttempts };
      await expect(new NovaProspectsSignalExecutor(resolver).execute(plan))
        .rejects.toThrow('maxProviderAttempts must be a positive safe integer');
      expect(resolver.requests).toEqual([]);
    },
  );

  test('preserves legacy plans without a shared budget', async (): Promise<void> => {
    const resolver = new RecordingResolver();
    const plan = planNovaProspectsSignal(signal());
    await new NovaProspectsSignalExecutor(resolver).execute(plan);
    expect(resolver.requests).toEqual(plan.requests);
    expect(resolver.requests).toHaveLength(3);
  });

  test('shares the attempt limit across every capability of a signal', async (): Promise<void> => {
    const executed: string[] = [];
    const provider: CrmDataProvider = {
      id: 'test-provider',
      capabilities: ['COMPANY_ENRICHMENT', 'PERSON_ENRICHMENT', 'EMAIL_VERIFY'],
      profile: { quality: 100, costEfficiency: 100, speed: 100 },
      async getStatus(): Promise<CrmProviderStatus> { return { available: true }; },
      async execute(request): Promise<CrmDataResult> {
        executed.push(request.capability);
        return {
          providerId: 'test-provider', capability: request.capability,
          outcome: 'FOUND', confidence: 1, data: {}, evidence: [],
        };
      },
    };
    const plan = planNovaProspectsSignal(signal({
      policy: {
        allowExternalEnrichment: true, allowEmailDiscovery: true, maxProviderAttempts: 1,
      },
    }));
    const result = await new NovaProspectsSignalExecutor(new CrmDataGateway([provider])).execute(plan);

    expect(executed).toEqual(['COMPANY_ENRICHMENT']);
    expect(result.items).toHaveLength(3);
    expect(result.items.slice(1).map((item) => item.response)).toEqual([
      { result: null, attempts: [], stoppedReason: 'MAX_PROVIDER_ATTEMPTS' },
      { result: null, attempts: [], stoppedReason: 'MAX_PROVIDER_ATTEMPTS' },
    ]);
  });

  test('executes the deterministic plan through the vendor-neutral gateway contract', async (): Promise<void> => {
    const resolver = new RecordingResolver();
    const executor = new NovaProspectsSignalExecutor(resolver);
    const plan = planNovaProspectsSignal(signal({
      kind: 'EMAIL_VERIFICATION_REQUIRED',
    }));

    const result = await executor.execute(plan);

    expect(resolver.requests).toEqual([
      {
        capability: 'EMAIL_VERIFY',
        input: { email: 'person@example.com' },
      },
    ]);
    expect(result.signalId).toBe('signal-1');
    expect(result.tenantId).toBe('tenant-a');
    expect(result.prospectId).toBe('prospect-1');
    expect(result.items).toHaveLength(1);
  });
});


describe('NovaProspects provider policy propagation', (): void => {
  test('propagates allowlist, preference and attempt budget to every planned request', (): void => {
    const plan = planNovaProspectsSignal(signal({
      policy: {
        allowExternalEnrichment: true,
        allowEmailDiscovery: true,
        allowedProviders: ['apollo', 'hunter'],
        preferredProviders: ['apollo'],
        maxProviderAttempts: 1,
      },
    }));

    expect(plan.requests.length).toBeGreaterThan(0);
    for (const request of plan.requests) {
      expect(request.allowedProviders).toEqual(['apollo', 'hunter']);
      expect(request.preferredProviders).toEqual(['apollo']);
      expect(request.maxProviderAttempts).toBe(1);
    }
  });

  test('rejects an invalid provider attempt budget before execution', (): void => {
    expect(() => planNovaProspectsSignal(signal({
      policy: {
        allowExternalEnrichment: true,
        allowEmailDiscovery: true,
        maxProviderAttempts: 0,
      },
    }))).toThrow('maxProviderAttempts must be a positive integer');
  });
});
