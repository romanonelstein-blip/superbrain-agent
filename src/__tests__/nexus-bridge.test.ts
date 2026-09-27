import { mkdtemp, mkdir, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { NexusBridge } from '../core/nexus.js';
import type { NexusDecisionRequest } from '../core/nexus.js';

async function fixture(output: string): Promise<{ bridge: NexusBridge; request: NexusDecisionRequest }> {
  const root = await mkdtemp(path.join(os.tmpdir(), 'superbrain-nexus-'));
  await mkdir(path.join(root, 'nexus1000'), { recursive: true });
  await writeFile(path.join(root, 'nexus1000', 'orchestrator.py'), '# fixture\n');
  await writeFile(path.join(root, 'nexus1000', 'neis.py'), '# fixture\n');
  const runner = path.join(root, 'runner.mjs');
  await writeFile(
    runner,
    `process.stdin.resume(); process.stdin.on('end', () => process.stdout.write(${JSON.stringify(output)}));`,
  );
  return {
    bridge: new NexusBridge({ corePath: root, pythonCommand: process.execPath, runnerPath: runner, timeoutMs: 5000 }),
    request: {
      question: 'Should this change proceed?',
      evidence: [{
        id: 'e1',
        claim: 'Tests passed',
        sourceId: 'ci',
        sourceFamily: 'tests',
        verified: true,
        citation: 'All tests passed',
        contentHash: 'sha256:fixture',
      }],
    },
  };
}

describe('NexusBridge', () => {
  test('is fail-closed when any canonical pipeline gate is false', async (): Promise<void> => {
    const { bridge, request } = await fixture(JSON.stringify({
      decision: 'YES',
      approved: true,
      pipelinePasses: { grand_council: true, neis: true, blinded_dissent: false, verifier: true },
      reasons: [],
      evidenceIds: ['e1'],
    }));
    const result = await bridge.evaluate(request);
    expect(result.decision).toBe('YES');
    expect(result.approved).toBe(false);
  });

  test('accepts approval only when all canonical gates are literal true', async (): Promise<void> => {
    const { bridge, request } = await fixture(JSON.stringify({
      decision: 'YES',
      approved: true,
      pipelinePasses: { grand_council: true, neis: true, blinded_dissent: true, verifier: true },
      reasons: ['all evidence gates passed'],
      evidenceIds: ['e1'],
    }));
    const result = await bridge.evaluate(request);
    expect(result.approved).toBe(true);
  });

  test('does not approve a NO decision even if a runner claims approval', async (): Promise<void> => {
    const { bridge, request } = await fixture(JSON.stringify({
      decision: 'NO',
      approved: true,
      pipelinePasses: { grand_council: true, neis: true, blinded_dissent: true, verifier: true },
      reasons: ['fixture disagreement'],
      evidenceIds: ['e1'],
    }));
    const result = await bridge.evaluate(request);
    expect(result.decision).toBe('NO');
    expect(result.approved).toBe(false);
  });

  test('does not expose raw runner errors', async (): Promise<void> => {
    const { bridge, request } = await fixture('not-json-secret-value');
    await expect(bridge.evaluate(request)).rejects.toThrow(
      'NEXUS evaluation failed or timed out. No approval was granted.',
    );
  });

  test('reports an unconfigured bridge without executing anything', async (): Promise<void> => {
    const bridge = new NexusBridge({ corePath: '' });
    const status = await bridge.getStatus();
    expect(status.ready).toBe(false);
  });
});
