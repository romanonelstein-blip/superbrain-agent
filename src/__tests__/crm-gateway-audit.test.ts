import {
  CrmDataGateway,
  type CrmDataProvider,
  type CrmDataRequest,
  type CrmDataResult,
  type CrmProviderStatus,
} from '../crm/data-gateway';
import type {
  CrmGatewayAuditEvent,
  CrmGatewayAuditSink,
} from '../crm/gateway-audit';

class AuditTestProvider implements CrmDataProvider {
  readonly id = 'audit-provider';
  readonly capabilities = ['EMAIL_VERIFY'] as const;
  readonly profile = {
    quality: 90,
    costEfficiency: 90,
    speed: 90,
  };

  async getStatus(): Promise<CrmProviderStatus> {
    return { available: true };
  }

  async execute(request: CrmDataRequest): Promise<CrmDataResult> {
    return {
      providerId: this.id,
      capability: request.capability,
      outcome: 'FOUND',
      confidence: 90,
      data: { status: 'valid' },
      evidence: [
        {
          source: this.id,
          retrievedAt: '2026-09-29T00:00:00.000Z',
        },
      ],
    };
  }
}

class CollectingAuditSink implements CrmGatewayAuditSink {
  readonly events: CrmGatewayAuditEvent[] = [];

  write(event: CrmGatewayAuditEvent): void {
    this.events.push(event);
  }
}

describe('CrmDataGateway audit events', (): void => {
  test('records provider outcomes without request PII', async (): Promise<void> => {
    const sink = new CollectingAuditSink();
    const gateway = new CrmDataGateway(
      [new AuditTestProvider()],
      undefined,
      {
        sink,
        now: (): Date => new Date('2026-09-29T00:00:00.000Z'),
      },
    );

    const response = await gateway.resolve({
      capability: 'EMAIL_VERIFY',
      input: {
        email: 'sensitive.person@example.com',
      },
    });

    expect(response.result?.providerId).toBe('audit-provider');
    expect(sink.events).toEqual([
      {
        type: 'PROVIDER_ATTEMPT',
        occurredAt: '2026-09-29T00:00:00.000Z',
        capability: 'EMAIL_VERIFY',
        providerId: 'audit-provider',
        state: 'FOUND',
      },
    ]);

    const serialized = JSON.stringify(sink.events);
    expect(serialized).not.toContain('sensitive.person@example.com');
    expect(serialized).not.toContain('input');
  });

  test('records a policy stop without exposing blocked request data', async (): Promise<void> => {
    const sink = new CollectingAuditSink();
    const gateway = new CrmDataGateway(
      [new AuditTestProvider()],
      undefined,
      {
        sink,
        now: (): Date => new Date('2026-09-29T00:01:00.000Z'),
      },
    );

    const response = await gateway.resolve({
      capability: 'EMAIL_VERIFY',
      input: { email: 'blocked@example.com' },
      allowedProviders: [],
    });

    expect(response.stoppedReason).toBe('NO_ALLOWED_PROVIDER');
    expect(sink.events).toEqual([
      {
        type: 'GATEWAY_STOPPED',
        occurredAt: '2026-09-29T00:01:00.000Z',
        capability: 'EMAIL_VERIFY',
        reason: 'NO_ALLOWED_PROVIDER',
      },
    ]);
    expect(JSON.stringify(sink.events)).not.toContain('blocked@example.com');
  });

  test('keeps read-only enrichment available when a best-effort audit sink fails', async (): Promise<void> => {
    const sink: CrmGatewayAuditSink = {
      write(): void {
        throw new Error('telemetry unavailable');
      },
    };
    const gateway = new CrmDataGateway(
      [new AuditTestProvider()],
      undefined,
      { sink },
    );

    await expect(gateway.resolve({
      capability: 'EMAIL_VERIFY',
      input: { email: 'person@example.com' },
    })).resolves.toMatchObject({
      result: {
        providerId: 'audit-provider',
        outcome: 'FOUND',
      },
    });
  });
});
