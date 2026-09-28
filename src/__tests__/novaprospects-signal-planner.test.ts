import type {
  CrmDataGatewayResponse,
  CrmDataRequest,
} from '../crm/data-gateway';
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
