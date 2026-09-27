import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  CommandMissionEvidenceProvider,
} from '../mobile/command-evidence-provider';

const directories: string[] = [];

function script(body: string): string {
  const directory = mkdtempSync(join(tmpdir(), 'superbrain-evidence-provider-'));
  directories.push(directory);
  const path = join(directory, 'provider.mjs');
  writeFileSync(path, body, 'utf8');
  return path;
}

function providerFor(path: string): CommandMissionEvidenceProvider {
  return new CommandMissionEvidenceProvider({
    command: process.execPath,
    args: [path],
    providerName: 'fixture-provider',
    timeoutMs: 5_000,
  });
}

afterEach((): void => {
  while (directories.length > 0) {
    const directory = directories.pop();
    if (directory) rmSync(directory, { recursive: true, force: true });
  }
});

describe('CommandMissionEvidenceProvider', (): void => {
  test('performs status handshake and validates a complete evidence bundle', async (): Promise<void> => {
    const path = script(`
      let input = '';
      for await (const chunk of process.stdin) input += chunk;
      const request = JSON.parse(input);
      if (request.type === 'status') {
        console.log(JSON.stringify({
          protocolVersion: 1,
          ready: true,
          interactiveMissionsAvailable: true,
          researchMissionsAvailable: true,
          configuredProviders: ['fixture-search', 'fixture-dissent']
        }));
      } else {
        console.log(JSON.stringify({
          protocolVersion: 1,
          verificationNote: 'Provider verified provenance.',
          evidence: [{
            id: 'e1',
            claim: 'Fixture claim',
            stance: 'support',
            sourceId: 'fixture-source',
            sourceFamily: 'fixture',
            reliability: 0.9,
            freshness: 0.8,
            relevance: 1,
            verified: true,
            citation: 'fixture://e1',
            contentHash: 'sha256:fixture'
          }],
          dissent: {
            completed: true,
            provider: 'fixture-dissent',
            requestId: 'dissent-1',
            evidence: [{
              id: 'd1',
              claim: 'Fixture challenge',
              stance: 'challenge',
              sourceId: 'fixture-dissent-source',
              sourceFamily: 'fixture',
              verified: true,
              citation: 'fixture://d1',
              contentHash: 'sha256:dissent'
            }]
          },
          draftResponses: [{ agent: 'fixture-agent', text: request.question, verified: true }],
          audit: [{ stage: 'provider', detail: 'Collected fixture evidence.' }]
        }));
      }
    `);
    const provider = providerFor(path);

    await expect(provider.getStatus()).resolves.toEqual({
      interactiveMissionsAvailable: true,
      researchMissionsAvailable: true,
      configuredProviders: ['fixture-search', 'fixture-dissent'],
    });

    const bundle = await provider.collect({
      runId: 'run-1',
      question: 'Check this',
      mode: 'research',
    });

    expect(bundle.evidence).toEqual([
      expect.objectContaining({
        id: 'e1',
        verified: true,
        citation: 'fixture://e1',
        contentHash: 'sha256:fixture',
      }),
    ]);
    expect(bundle.dissent).toEqual(expect.objectContaining({
      completed: true,
      provider: 'fixture-dissent',
      evidence: [expect.objectContaining({ id: 'd1', stance: 'challenge' })],
    }));
    expect(bundle.draftResponses).toEqual([
      expect.objectContaining({ agent: 'fixture-agent', text: 'Check this', verified: true }),
    ]);
  });

  test('rejects verified evidence without citation and contentHash', async (): Promise<void> => {
    const path = script(`
      let input = '';
      for await (const chunk of process.stdin) input += chunk;
      const request = JSON.parse(input);
      if (request.type === 'status') {
        console.log(JSON.stringify({
          protocolVersion: 1,
          ready: true,
          interactiveMissionsAvailable: true,
          researchMissionsAvailable: false
        }));
      } else {
        console.log(JSON.stringify({
          protocolVersion: 1,
          evidence: [{
            id: 'e1',
            claim: 'Invalid verified claim',
            sourceId: 'fixture-source',
            sourceFamily: 'fixture',
            verified: true
          }]
        }));
      }
    `);
    const provider = providerFor(path);

    await expect(provider.collect({
      runId: 'run-2',
      question: 'Reject invalid evidence',
      mode: 'ask',
    })).rejects.toThrow('verified evidence requires citation and contentHash');
  });

  test('reports unavailable when the provider process fails its status handshake', async (): Promise<void> => {
    const path = script(`
      process.exit(12);
    `);
    const provider = providerFor(path);

    await expect(provider.getStatus()).resolves.toEqual({
      interactiveMissionsAvailable: false,
      researchMissionsAvailable: false,
      configuredProviders: [],
    });
  });

  test('rejects extra logs mixed into stdout instead of accepting ambiguous JSON', async (): Promise<void> => {
    const path = script(`
      console.log('debug log that must not be parsed');
      console.log(JSON.stringify({ protocolVersion: 1, ready: true }));
    `);
    const provider = providerFor(path);

    await expect(provider.getStatus()).resolves.toEqual({
      interactiveMissionsAvailable: false,
      researchMissionsAvailable: false,
      configuredProviders: [],
    });
  });
});
