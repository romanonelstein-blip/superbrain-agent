import 'dotenv/config';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { MissionControlServer, UnavailableMissionExecutor } from './mission-control.js';

interface PackageMetadata {
  version: string;
}

interface MobileContract {
  apiVersion: string;
  capabilities: Array<{ id: string }>;
}

async function readJson<T>(path: string): Promise<T> {
  return JSON.parse(await readFile(path, 'utf8')) as T;
}

async function main(): Promise<void> {
  const root = process.cwd();
  const token = process.env.SUPERBRAIN_MISSION_CONTROL_TOKEN?.trim() ?? '';
  if (token.length < 20) {
    throw new Error('Set SUPERBRAIN_MISSION_CONTROL_TOKEN to a secret with at least 20 characters.');
  }

  const host = process.env.SUPERBRAIN_MISSION_CONTROL_HOST?.trim() || '127.0.0.1';
  const port = Number.parseInt(process.env.SUPERBRAIN_MISSION_CONTROL_PORT ?? '8787', 10);
  if (!Number.isInteger(port) || port < 0 || port > 65535) throw new Error('Invalid Mission Control port.');

  const loopbackHosts = new Set(['127.0.0.1', '::1', 'localhost']);
  if (!loopbackHosts.has(host) && process.env.SUPERBRAIN_ALLOW_INSECURE_HTTP !== '1') {
    throw new Error(
      'Mission Control uses HTTP. Refusing a non-loopback bind. Put it behind HTTPS or explicitly set SUPERBRAIN_ALLOW_INSECURE_HTTP=1 for a controlled environment.',
    );
  }

  const [pkg, contract] = await Promise.all([
    readJson<PackageMetadata>(join(root, 'package.json')),
    readJson<MobileContract>(join(root, 'shared', 'superbrain-mobile-contract.json')),
  ]);

  const server = new MissionControlServer({
    token,
    host,
    port,
    dataPath: process.env.SUPERBRAIN_MISSION_CONTROL_DATA
      ?? join(root, '.superbrain', 'mission-control', 'missions.json'),
    canonicalRuntime: 'NEXUS-1000',
    superBrainVersion: pkg.version,
    apiVersion: contract.apiVersion,
    capabilities: contract.capabilities.map((capability): string => capability.id),
    executor: new UnavailableMissionExecutor(),
  });

  const address = await server.listen();
  console.log(`SuperBrain Mission Control listening on ${address.url}`);
  console.log('Mission execution is fail-closed until a real MissionExecutor is connected.');

  let stopping = false;
  const shutdown = async (): Promise<void> => {
    if (stopping) return;
    stopping = true;
    await server.close();
  };
  process.once('SIGINT', (): void => { void shutdown(); });
  process.once('SIGTERM', (): void => { void shutdown(); });
}

void main().catch((error: unknown): void => {
  console.error(error instanceof Error ? error.message : 'Mission Control failed to start.');
  process.exitCode = 1;
});
