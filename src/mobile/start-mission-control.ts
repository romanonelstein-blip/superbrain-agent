import 'dotenv/config';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { NexusBridge } from '../core/nexus.js';
import { CommandMissionEvidenceProvider } from './command-evidence-provider.js';
import { HttpResearchEvidenceProvider } from './http-research-evidence-provider.js';
import { MissionControlServer } from './mission-control.js';
import {
  NexusMissionExecutor,
  type MissionEvidenceProvider,
  UnavailableMissionEvidenceProvider,
} from './nexus-mission-executor.js';

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

function parseEvidenceProviderArgs(value: string | undefined): string[] {
  if (!value?.trim()) return [];
  const parsed = JSON.parse(value) as unknown;
  if (!Array.isArray(parsed) || parsed.some((item): boolean => typeof item !== 'string')) {
    throw new Error('SUPERBRAIN_EVIDENCE_PROVIDER_ARGS must be a JSON array of strings.');
  }
  return parsed as string[];
}

function parseResearchInteger(name: string, fallback: number): number {
  const raw = process.env[name]?.trim();
  if (!raw) return fallback;
  const value = Number.parseInt(raw, 10);
  if (!Number.isInteger(value)) throw new Error(`${name} must be an integer.`);
  return value;
}

function parseResearchBoolean(name: string, fallback: boolean): boolean {
  const raw = process.env[name]?.trim();
  if (!raw) return fallback;
  if (raw === '1' || raw.toLowerCase() === 'true') return true;
  if (raw === '0' || raw.toLowerCase() === 'false') return false;
  throw new Error(`${name} must be true/false or 1/0.`);
}

function evidenceProviderFromEnvironment(): MissionEvidenceProvider {
  const command = process.env.SUPERBRAIN_EVIDENCE_PROVIDER_COMMAND?.trim();
  const primaryEndpoint = process.env.SUPERBRAIN_RESEARCH_PRIMARY_ENDPOINT?.trim();
  const dissentEndpoint = process.env.SUPERBRAIN_RESEARCH_DISSENT_ENDPOINT?.trim();

  if (command && (primaryEndpoint || dissentEndpoint)) {
    throw new Error('Configure either command evidence mode or HTTP research mode, not both.');
  }

  if (primaryEndpoint || dissentEndpoint) {
    if (!primaryEndpoint || !dissentEndpoint) {
      throw new Error('HTTP research mode requires both primary and dissent endpoints.');
    }
    return new HttpResearchEvidenceProvider({
      primary: {
        endpoint: primaryEndpoint,
        providerName: process.env.SUPERBRAIN_RESEARCH_PRIMARY_NAME?.trim() || 'primary-research',
        ...(process.env.SUPERBRAIN_RESEARCH_PRIMARY_TOKEN
          ? { bearerToken: process.env.SUPERBRAIN_RESEARCH_PRIMARY_TOKEN }
          : {}),
      },
      dissent: {
        endpoint: dissentEndpoint,
        providerName: process.env.SUPERBRAIN_RESEARCH_DISSENT_NAME?.trim() || 'dissent-research',
        ...(process.env.SUPERBRAIN_RESEARCH_DISSENT_TOKEN
          ? { bearerToken: process.env.SUPERBRAIN_RESEARCH_DISSENT_TOKEN }
          : {}),
      },
      minimumResearchPrimarySources: parseResearchInteger(
        'SUPERBRAIN_RESEARCH_MIN_PRIMARY_SOURCES',
        2,
      ),
      minimumResearchPrimaryFamilies: parseResearchInteger(
        'SUPERBRAIN_RESEARCH_MIN_PRIMARY_FAMILIES',
        2,
      ),
      minimumDissentSources: parseResearchInteger(
        'SUPERBRAIN_RESEARCH_MIN_DISSENT_SOURCES',
        1,
      ),
      requireDistinctDissentFamily: parseResearchBoolean(
        'SUPERBRAIN_RESEARCH_REQUIRE_DISTINCT_DISSENT_FAMILY',
        true,
      ),
      allowedSourceHosts: (process.env.SUPERBRAIN_RESEARCH_ALLOWED_HOSTS ?? '')
        .split(',')
        .map((host): string => host.trim())
        .filter(Boolean),
    });
  }

  if (!command) return new UnavailableMissionEvidenceProvider();

  const timeoutMs = Number.parseInt(process.env.SUPERBRAIN_EVIDENCE_PROVIDER_TIMEOUT_MS ?? '60000', 10);
  if (!Number.isInteger(timeoutMs)) throw new Error('SUPERBRAIN_EVIDENCE_PROVIDER_TIMEOUT_MS must be an integer.');

  return new CommandMissionEvidenceProvider({
    command,
    args: parseEvidenceProviderArgs(process.env.SUPERBRAIN_EVIDENCE_PROVIDER_ARGS),
    providerName: process.env.SUPERBRAIN_EVIDENCE_PROVIDER_NAME?.trim() || 'configured-evidence-provider',
    timeoutMs,
  });
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
    executor: new NexusMissionExecutor(
      new NexusBridge(),
      evidenceProviderFromEnvironment(),
    ),
  });

  const address = await server.listen();
  console.log(`SuperBrain Mission Control listening on ${address.url}`);
  console.log('NEXUS is connected through the mission executor.');
  console.log(
    process.env.SUPERBRAIN_EVIDENCE_PROVIDER_COMMAND
      ? 'Configured command evidence provider will be validated before missions become available.'
      : process.env.SUPERBRAIN_RESEARCH_PRIMARY_ENDPOINT
        ? 'Configured HTTP research providers will be validated before missions become available.'
        : 'Mission execution remains fail-closed until an evidence provider is configured.',
  );

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
