import type {
  JsonHttpRequest,
  JsonHttpResponse,
  JsonHttpTransport,
} from '../crm/http-json-transport';
import { ClayDataProvider } from '../crm/providers/clay-provider';

class QueueTransport implements JsonHttpTransport {
  readonly requests: JsonHttpRequest[] = [];

  constructor(private readonly responses: JsonHttpResponse[]) {}

  async request(input: JsonHttpRequest): Promise<JsonHttpResponse> {
    this.requests.push(input);
    const response = this.responses.shift();
    if (!response) throw new Error('No queued response');
    return response;
  }
}

describe('ClayDataProvider', (): void => {
  test('advertises only the configured capabilities', (): void => {
    const provider = new ClayDataProvider({
      apiKey: 'clay-secret',
      personEnrichmentRoutineId: 'function:person',
    });

    expect(provider.capabilities).toEqual(['PERSON_ENRICHMENT']);
  });

  test('runs person enrichment with header auth and an opaque item id', async (): Promise<void> => {
    const transport = new QueueTransport([
      { status: 202, body: { routine_run_id: 'run-1' } },
      {
        status: 200,
        body: {
          status: 'complete',
          data: [
            {
              id: 'superbrain-item',
              status: 'complete',
              result: {
                'Enrich person': {
                  name: 'Test Person',
                  title: 'Head of Sales',
                },
              },
            },
          ],
        },
      },
    ]);

    const provider = new ClayDataProvider({
      apiKey: 'clay-secret',
      personEnrichmentRoutineId: 'function:person',
      transport,
      sleep: async (): Promise<void> => {},
    });

    const response = await provider.execute({
      capability: 'PERSON_ENRICHMENT',
      input: { email: 'person@example.com' },
    });

    expect(response.outcome).toBe('FOUND');
    expect(response.data).toEqual({
      name: 'Test Person',
      title: 'Head of Sales',
    });

    expect(transport.requests[0]?.headers?.['clay-api-key']).toBe('clay-secret');
    expect(transport.requests[0]?.url).not.toContain('clay-secret');
    expect(transport.requests[0]?.body).toEqual({
      items: [
        {
          id: 'superbrain-item',
          inputs: { Email: 'person@example.com' },
        },
      ],
    });
  });

  test('maps company enrichment to Clay Company Identifier without exposing tenant data', async (): Promise<void> => {
    const transport = new QueueTransport([
      { status: 202, body: { routineRunId: 'run-2' } },
      {
        status: 200,
        body: {
          status: 'complete',
          data: [
            {
              id: 'superbrain-item',
              status: 'complete',
              result: {
                'Enrich Company': {
                  name: 'Example',
                  domain: 'example.com',
                },
              },
            },
          ],
        },
      },
    ]);

    const provider = new ClayDataProvider({
      apiKey: 'clay-secret',
      companyEnrichmentRoutineId: 'function:company',
      transport,
      sleep: async (): Promise<void> => {},
    });

    const response = await provider.execute({
      capability: 'COMPANY_ENRICHMENT',
      input: {
        domain: 'example.com',
      },
    });

    expect(response.outcome).toBe('FOUND');
    expect(transport.requests[0]?.body).toEqual({
      items: [
        {
          id: 'superbrain-item',
          inputs: { 'Company Identifier': 'example.com' },
        },
      ],
    });
  });

  test('returns unavailable when no routine ids are configured', async (): Promise<void> => {
    const provider = new ClayDataProvider({
      apiKey: 'clay-secret',
    });

    await expect(provider.getStatus()).resolves.toEqual({
      available: false,
      reason: 'missing_routine_ids',
    });
  });

  test('fails closed when a routine never completes', async (): Promise<void> => {
    const transport = new QueueTransport([
      { status: 202, body: { routine_run_id: 'run-3' } },
      { status: 200, body: { status: 'in_progress', data: [] } },
      { status: 200, body: { status: 'in_progress', data: [] } },
    ]);

    const provider = new ClayDataProvider({
      apiKey: 'clay-secret',
      personEnrichmentRoutineId: 'function:person',
      transport,
      maxPollAttempts: 2,
      pollIntervalMs: 0,
      sleep: async (): Promise<void> => {},
    });

    await expect(provider.execute({
      capability: 'PERSON_ENRICHMENT',
      input: { email: 'person@example.com' },
    })).rejects.toThrow('did not complete');
  });
});
