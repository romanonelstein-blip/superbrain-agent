import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http';
import {
  HttpResearchEvidenceProvider,
} from '../mobile/http-research-evidence-provider';

interface TestServer {
  server: Server;
  baseUrl: string;
}

const servers: Server[] = [];

async function readJson(request: IncomingMessage): Promise<Record<string, unknown>> {
  const chunks: Buffer[] = [];
  for await (const chunk of request) chunks.push(Buffer.from(chunk));
  return JSON.parse(Buffer.concat(chunks).toString('utf8')) as Record<string, unknown>;
}

async function createFixtureServer(): Promise<TestServer> {
  const server = createServer((request: IncomingMessage, response: ServerResponse): void => {
    void (async (): Promise<void> => {
      const path = new URL(request.url ?? '/', 'http://fixture.local').pathname;

      if (path === '/primary' || path === '/dissent') {
        const body = await readJson(request);
        response.setHeader('Content-Type', 'application/json');
        if (body.type === 'status') {
          response.end(JSON.stringify({ protocolVersion: 1, ready: true }));
          return;
        }
        const sourcePath = path === '/primary' ? '/source-a' : '/source-b';
        const address = server.address();
        if (!address || typeof address === 'string') throw new Error('Missing fixture address.');
        response.end(JSON.stringify({
          protocolVersion: 1,
          results: [{
            url: `http://127.0.0.1:${address.port}${sourcePath}`,
            title: path === '/primary' ? 'Primary source' : 'Dissent source',
            snippet: path === '/primary'
              ? 'Primary discovery snippet.'
              : 'Independent challenge snippet.',
          }],
        }));
        return;
      }

      if (path === '/source-a') {
        response.setHeader('Content-Type', 'text/html; charset=utf-8');
        response.end('<html><head><title>Alpha</title></head><body><script>ignored()</script><p>Primary source body with concrete evidence.</p></body></html>');
        return;
      }

      if (path === '/source-b') {
        response.setHeader('Content-Type', 'text/plain; charset=utf-8');
        response.end('Dissent source body that challenges the primary case.');
        return;
      }

      if (path === '/too-large') {
        response.setHeader('Content-Type', 'text/plain');
        response.end('x'.repeat(4096));
        return;
      }

      response.statusCode = 404;
      response.end();
    })().catch((): void => {
      response.statusCode = 500;
      response.end();
    });
  });
  await new Promise<void>((resolve, reject): void => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', (): void => {
      server.off('error', reject);
      resolve();
    });
  });
  servers.push(server);
  const address = server.address();
  if (!address || typeof address === 'string') throw new Error('Fixture server did not bind.');
  return { server, baseUrl: `http://127.0.0.1:${address.port}` };
}

afterEach(async (): Promise<void> => {
  while (servers.length > 0) {
    const server = servers.pop();
    if (!server) continue;
    await new Promise<void>((resolve): void => {
      server.close((): void => { resolve(); });
    });
  }
});

describe('HttpResearchEvidenceProvider', (): void => {
  test('discovers, fetches, hashes and separates primary from dissent evidence', async (): Promise<void> => {
    const fixture = await createFixtureServer();
    const provider = new HttpResearchEvidenceProvider({
      primary: {
        endpoint: `${fixture.baseUrl}/primary`,
        providerName: 'primary-fixture',
      },
      dissent: {
        endpoint: `${fixture.baseUrl}/dissent`,
        providerName: 'dissent-fixture',
      },
      allowPrivateNetworksForTesting: true,
      allowInsecureHttpForTesting: true,
      maxResultsPerProvider: 3,
      minimumResearchPrimarySources: 1,
      minimumResearchPrimaryFamilies: 1,
      requireDistinctDissentFamily: false,
    });

    await expect(provider.getStatus()).resolves.toEqual({
      interactiveMissionsAvailable: true,
      researchMissionsAvailable: true,
      configuredProviders: ['primary-fixture', 'dissent-fixture'],
    });

    const bundle = await provider.collect({
      runId: 'run-1',
      question: 'Is the fixture supported?',
      mode: 'research',
    });

    expect(bundle.evidence).toHaveLength(1);
    expect(bundle.evidence[0]).toEqual(expect.objectContaining({
      verified: true,
      stance: 'neutral',
      provider: 'primary-fixture',
      sourceFamily: '127.0.0.1',
      contentType: 'text/html',
    }));
    expect(bundle.evidence[0].contentHash).toMatch(/^sha256:[a-f0-9]{64}$/);
    expect(bundle.evidence[0].claim).toContain('Primary source body with concrete evidence.');
    expect(bundle.evidence[0].claim).not.toContain('ignored()');

    expect(bundle.dissent).toEqual(expect.objectContaining({
      completed: true,
      provider: 'dissent-fixture',
      evidence: [
        expect.objectContaining({
          verified: true,
          stance: 'challenge',
          provider: 'dissent-fixture',
          contentType: 'text/plain',
        }),
      ],
    }));
    expect(bundle.verificationNote).toContain('Research diversity gate passed');
    expect(bundle.verificationNote).toContain('independent dissent source');
  });

  test('research mode fails closed when primary evidence lacks source diversity', async (): Promise<void> => {
    const fixture = await createFixtureServer();
    const provider = new HttpResearchEvidenceProvider({
      primary: {
        endpoint: `${fixture.baseUrl}/primary`,
        providerName: 'primary-fixture',
      },
      dissent: {
        endpoint: `${fixture.baseUrl}/dissent`,
        providerName: 'dissent-fixture',
      },
      allowPrivateNetworksForTesting: true,
      allowInsecureHttpForTesting: true,
    });

    await expect(provider.collect({
      runId: 'run-diversity',
      question: 'Require independent primary sources',
      mode: 'research',
    })).rejects.toThrow('at least 2 unique primary source');
  });

  test('dissent cannot reuse the same source family when independence is required', async (): Promise<void> => {
    const fixture = await createFixtureServer();
    const provider = new HttpResearchEvidenceProvider({
      primary: {
        endpoint: `${fixture.baseUrl}/primary`,
        providerName: 'primary-fixture',
      },
      dissent: {
        endpoint: `${fixture.baseUrl}/dissent`,
        providerName: 'dissent-fixture',
      },
      allowPrivateNetworksForTesting: true,
      allowInsecureHttpForTesting: true,
      minimumResearchPrimarySources: 1,
      minimumResearchPrimaryFamilies: 1,
      requireDistinctDissentFamily: true,
    });

    await expect(provider.collect({
      runId: 'run-dissent-family',
      question: 'Reject same-family dissent',
      mode: 'research',
    })).rejects.toThrow('independent dissent source');
  });

  test('refuses ordinary HTTP endpoints outside explicit test mode', (): void => {
    expect((): HttpResearchEvidenceProvider => new HttpResearchEvidenceProvider({
      primary: { endpoint: 'http://example.com/search', providerName: 'primary' },
      dissent: { endpoint: 'https://example.org/search', providerName: 'dissent' },
    })).toThrow('requires HTTPS');
  });

  test('status fails closed when private network discovery is not explicitly enabled', async (): Promise<void> => {
    const fixture = await createFixtureServer();
    const provider = new HttpResearchEvidenceProvider({
      primary: {
        endpoint: `${fixture.baseUrl}/primary`,
        providerName: 'primary-fixture',
      },
      dissent: {
        endpoint: `${fixture.baseUrl}/dissent`,
        providerName: 'dissent-fixture',
      },
      allowInsecureHttpForTesting: true,
    });

    await expect(provider.getStatus()).resolves.toEqual({
      interactiveMissionsAvailable: false,
      researchMissionsAvailable: false,
      configuredProviders: [],
    });
  });

  test('rejects identical primary and dissent provider identities', (): void => {
    expect((): HttpResearchEvidenceProvider => new HttpResearchEvidenceProvider({
      primary: { endpoint: 'https://search.example.test/api', providerName: 'same' },
      dissent: { endpoint: 'https://search.example.test/api', providerName: 'same' },
    })).toThrow('independently identified');
  });
});
