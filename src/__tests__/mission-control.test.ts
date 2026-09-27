import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  MissionControlServer,
  type MissionExecutionInput,
  type MissionExecutionResult,
  type MissionExecutor,
  type MissionExecutorStatus,
  UnavailableMissionExecutor,
} from '../mobile/mission-control';

const TOKEN = 'test-token-12345678901234567890';

class TestExecutor implements MissionExecutor {
  async getStatus(): Promise<MissionExecutorStatus> {
    return {
      interactiveMissionsAvailable: true,
      researchMissionsAvailable: true,
      configuredProviders: ['test-provider'],
    };
  }

  async execute(input: MissionExecutionInput): Promise<MissionExecutionResult> {
    return {
      nexusFinalValue: input.mode === 'research' ? 'YES' : 'NO',
      verificationNote: 'Fixture result',
      draftResponses: [{ agent: 'fixture', text: input.question, verified: true }],
      evidence: [{
        id: 'evidence-1',
        claim: 'Fixture evidence',
        verified: true,
        sourceId: 'fixture-source',
        sourceFamily: 'test',
        citation: 'fixture://evidence-1',
      }],
      audit: [{ stage: 'fixture', detail: `Executed ${input.mode}` }],
    };
  }
}

interface TestContext {
  directory: string;
  server: MissionControlServer;
  baseUrl: string;
}

const contexts: TestContext[] = [];

async function createTestServer(executor: MissionExecutor = new TestExecutor(), dataPath?: string): Promise<TestContext> {
  const directory = dataPath ? join(dataPath, '..') : mkdtempSync(join(tmpdir(), 'superbrain-mobile-api-'));
  const filePath = dataPath ?? join(directory, 'missions.json');
  const server = new MissionControlServer({
    token: TOKEN,
    host: '127.0.0.1',
    port: 0,
    dataPath: filePath,
    superBrainVersion: '9.9.9-test',
    apiVersion: '1',
    capabilities: ['runtime_status', 'mission_list', 'mission_ask', 'master_decision'],
    executor,
  });
  const address = await server.listen();
  const context = { directory, server, baseUrl: address.url };
  contexts.push(context);
  return context;
}

async function api(
  context: TestContext,
  path: string,
  init: RequestInit = {},
  token: string = TOKEN,
): Promise<Response> {
  return fetch(`${context.baseUrl}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(init.body ? { 'Content-Type': 'application/json' } : {}),
      ...init.headers,
    },
  });
}

afterEach(async (): Promise<void> => {
  while (contexts.length > 0) {
    const context = contexts.pop();
    if (!context) continue;
    await context.server.close();
    rmSync(context.directory, { recursive: true, force: true });
  }
});

describe('MissionControlServer', (): void => {
  test('requires bearer auth and exposes runtime compatibility metadata', async (): Promise<void> => {
    const context = await createTestServer();

    const unauthorized = await fetch(`${context.baseUrl}/api/system/status`);
    expect(unauthorized.status).toBe(401);

    const response = await api(context, '/api/system/status');
    expect(response.status).toBe(200);
    const body = await response.json() as Record<string, unknown>;
    expect(body.canonicalRuntime).toBe('NEXUS-1000');
    expect(body.superBrainVersion).toBe('9.9.9-test');
    expect(body.apiVersion).toBe('1');
    expect(body.interactiveMissionsAvailable).toBe(true);
    expect(body.configuredProviders).toEqual(['test-provider']);
    expect(body.capabilities).toEqual(expect.arrayContaining(['runtime_status', 'mission_ask']));
  });

  test('runs, stores and reloads missions plus master decisions', async (): Promise<void> => {
    const context = await createTestServer();
    const dataPath = join(context.directory, 'missions.json');

    const start = await api(context, '/api/missions/research', {
      method: 'POST',
      body: JSON.stringify({ mission: 'Check the fixture' }),
    });
    expect(start.status).toBe(200);
    const started = await start.json() as { runId: string; nexusFinalValue: string };
    expect(started.nexusFinalValue).toBe('YES');

    const decision = await api(context, `/api/missions/${started.runId}/master-decision`, {
      method: 'POST',
      body: JSON.stringify({ action: 'ACCEPT', note: 'Reviewed on iPhone' }),
    });
    expect(decision.status).toBe(200);

    const detailResponse = await api(context, `/api/missions/${started.runId}`);
    const detail = await detailResponse.json() as {
      run: { status: string; finalValue: string };
      evidence: unknown[];
      audit: unknown[];
      masterDecisions: Array<{ action: string; note: string }>;
    };
    expect(detail.run).toMatchObject({ status: 'completed', finalValue: 'YES' });
    expect(detail.evidence).toHaveLength(1);
    expect(detail.audit.length).toBeGreaterThanOrEqual(3);
    expect(detail.masterDecisions).toEqual([
      expect.objectContaining({ action: 'ACCEPT', note: 'Reviewed on iPhone' }),
    ]);

    await context.server.close();
    const index = contexts.indexOf(context);
    if (index >= 0) contexts.splice(index, 1);

    const restarted = await createTestServer(new TestExecutor(), dataPath);
    const listResponse = await api(restarted, '/api/missions');
    const list = await listResponse.json() as { missions: Array<{ runId: string; status: string }> };
    expect(list.missions).toEqual([
      expect.objectContaining({ runId: started.runId, status: 'completed' }),
    ]);
  });

  test('fails closed when no real mission executor is configured', async (): Promise<void> => {
    const context = await createTestServer(new UnavailableMissionExecutor());

    const statusResponse = await api(context, '/api/system/status');
    const status = await statusResponse.json() as { interactiveMissionsAvailable: boolean };
    expect(status.interactiveMissionsAvailable).toBe(false);

    const start = await api(context, '/api/missions/ask', {
      method: 'POST',
      body: JSON.stringify({ mission: 'Do not fake this result' }),
    });
    expect(start.status).toBe(503);

    const listResponse = await api(context, '/api/missions');
    const list = await listResponse.json() as { missions: unknown[] };
    expect(list.missions).toEqual([]);
  });
});
