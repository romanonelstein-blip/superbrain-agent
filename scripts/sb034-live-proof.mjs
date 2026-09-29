import { mkdir, writeFile } from 'node:fs/promises';
import { dirname } from 'node:path';
import { NexusBridge } from '../dist/core/nexus.js';
import { CommandMissionEvidenceProvider } from '../dist/mobile/command-evidence-provider.js';
import { HttpResearchEvidenceProvider } from '../dist/mobile/http-research-evidence-provider.js';
import {
  NexusMissionExecutor,
  UnavailableMissionEvidenceProvider,
} from '../dist/mobile/nexus-mission-executor.js';

const requiredGates = ['grand_council', 'neis', 'blinded_dissent', 'verifier'];
const sha = process.env.GITHUB_SHA?.trim() || process.env.SUPERBRAIN_PROOF_SHA?.trim() || 'unknown';
const reportPath = process.env.SUPERBRAIN_SB034_REPORT?.trim() || 'artifacts/sb034-live-proof.json';

const report = {
  protocol: 'SB-034-live-proof-v2',
  sha,
  requiredGates,
  status: 'BLOCKED',
  reason: '',
  providerMode: 'unconfigured',
  configuredProviders: [],
  positiveRun: null,
  negativeRun: null,
};

function requiredEnv(name) {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required.`);
  return value;
}

function integerEnv(name, fallback) {
  const raw = process.env[name]?.trim();
  if (!raw) return fallback;
  const parsed = Number.parseInt(raw, 10);
  if (!Number.isInteger(parsed)) throw new Error(`${name} must be an integer.`);
  return parsed;
}

function booleanEnv(name, fallback) {
  const raw = process.env[name]?.trim();
  if (!raw) return fallback;
  if (raw === '1' || raw.toLowerCase() === 'true') return true;
  if (raw === '0' || raw.toLowerCase() === 'false') return false;
  throw new Error(`${name} must be true/false or 1/0.`);
}

function commandArgs() {
  const raw = process.env.SUPERBRAIN_EVIDENCE_PROVIDER_ARGS?.trim();
  if (!raw) return [];
  const parsed = JSON.parse(raw);
  if (!Array.isArray(parsed) || parsed.some(item => typeof item !== 'string')) {
    throw new Error('SUPERBRAIN_EVIDENCE_PROVIDER_ARGS must be a JSON array of strings.');
  }
  return parsed;
}

function providerFromEnvironment() {
  const command = process.env.SUPERBRAIN_EVIDENCE_PROVIDER_COMMAND?.trim();
  const primaryEndpoint = process.env.SUPERBRAIN_RESEARCH_PRIMARY_ENDPOINT?.trim();
  const dissentEndpoint = process.env.SUPERBRAIN_RESEARCH_DISSENT_ENDPOINT?.trim();
  const hasHttp = Boolean(primaryEndpoint || dissentEndpoint);

  if (command && hasHttp) {
    throw new Error('Configure either command evidence mode or HTTP research mode, not both.');
  }

  if (hasHttp) {
    if (!primaryEndpoint || !dissentEndpoint) {
      throw new Error('HTTP research proof requires both primary and dissent endpoints.');
    }
    report.providerMode = 'http-research';
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
      minimumResearchPrimarySources: integerEnv('SUPERBRAIN_RESEARCH_MIN_PRIMARY_SOURCES', 2),
      minimumResearchPrimaryFamilies: integerEnv('SUPERBRAIN_RESEARCH_MIN_PRIMARY_FAMILIES', 2),
      minimumDissentSources: integerEnv('SUPERBRAIN_RESEARCH_MIN_DISSENT_SOURCES', 1),
      requireDistinctDissentFamily: booleanEnv(
        'SUPERBRAIN_RESEARCH_REQUIRE_DISTINCT_DISSENT_FAMILY',
        true,
      ),
      allowedSourceHosts: (process.env.SUPERBRAIN_RESEARCH_ALLOWED_HOSTS ?? '')
        .split(',')
        .map(host => host.trim())
        .filter(Boolean),
    });
  }

  if (command) {
    report.providerMode = 'command';
    return new CommandMissionEvidenceProvider({
      command,
      args: commandArgs(),
      providerName: process.env.SUPERBRAIN_EVIDENCE_PROVIDER_NAME?.trim()
        || 'configured-evidence-provider',
      timeoutMs: integerEnv('SUPERBRAIN_EVIDENCE_PROVIDER_TIMEOUT_MS', 60_000),
    });
  }

  throw new Error('No live evidence provider is configured.');
}

class CapturingProvider {
  constructor(inner) {
    this.inner = inner;
    this.bundle = null;
  }

  async getStatus() {
    return this.inner.getStatus();
  }

  async collect(input) {
    const bundle = await this.inner.collect(input);
    this.bundle = bundle;
    return bundle;
  }
}

function provenanceRecord(item, role) {
  return {
    role,
    id: item.id,
    sourceId: item.sourceId,
    sourceFamily: item.sourceFamily,
    trustBoundary: item.trustBoundary ?? null,
    verified: item.verified === true,
    citation: item.citation ?? null,
    contentHash: item.contentHash ?? null,
    provider: item.provider ?? null,
    providerModel: item.providerModel ?? null,
    providerRequestId: item.providerRequestId ?? null,
  };
}

async function persistReport() {
  await mkdir(dirname(reportPath), { recursive: true });
  await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
}

async function main() {
  try {
    if (sha === 'unknown') throw new Error('Exact tested Git SHA is required for SB-034 proof.');

    const question = requiredEnv('SUPERBRAIN_SB034_QUESTION');
    const nexusRoot = requiredEnv('SUPERBRAIN_NEXUS_ROOT');
    const provider = providerFromEnvironment();
    const capturingProvider = new CapturingProvider(provider);
    const engine = new NexusBridge({ corePath: nexusRoot });
    const executor = new NexusMissionExecutor(engine, capturingProvider);

    const status = await executor.getStatus();
    report.configuredProviders = status.configuredProviders;
    if (!status.researchMissionsAvailable) {
      throw new Error('Live provider and NEXUS-1000 must both be ready for a research mission.');
    }

    const runId = `sb034-${sha.slice(0, 12)}`;
    const result = await executor.execute({
      runId,
      question,
      mode: 'research',
    });
    const bundle = capturingProvider.bundle;
    if (!bundle) throw new Error('Live provider bundle was not captured from the executed mission.');

    const gateAudit = Object.fromEntries(requiredGates.map(gate => {
      const detail = result.audit.find(item => item.stage === `nexus_gate:${gate}`)?.detail ?? 'MISSING';
      return [gate, detail];
    }));
    const allGatesPass = requiredGates.every(gate => gateAudit[gate] === 'PASS');

    const provenance = [
      ...bundle.evidence.map(item => provenanceRecord(item, 'primary')),
      ...(bundle.dissent?.evidence ?? []).map(item => provenanceRecord(item, 'dissent')),
    ];
    const provenanceBacked = provenance.length > 0 && provenance.every(item =>
      item.verified
      && typeof item.citation === 'string' && item.citation.length > 0
      && typeof item.contentHash === 'string' && item.contentHash.length > 0
      && typeof item.provider === 'string' && item.provider.length > 0
      && typeof item.trustBoundary === 'string' && item.trustBoundary.length > 0
    );

    report.positiveRun = {
      runId,
      finalValue: result.nexusFinalValue,
      gateAudit,
      provenanceBacked,
      evidence: provenance,
    };

    if (result.nexusFinalValue !== 'YES') {
      throw new Error('Live NEXUS run did not produce an approved YES result.');
    }
    if (!allGatesPass) {
      throw new Error('Live NEXUS run did not pass every required canonical gate.');
    }
    if (!provenanceBacked) {
      throw new Error('Live provider evidence is missing verified provenance fields.');
    }

    const failClosedExecutor = new NexusMissionExecutor(
      engine,
      new UnavailableMissionEvidenceProvider(),
    );
    let denied = false;
    let failure = '';
    try {
      await failClosedExecutor.execute({
        runId: `${runId}-negative`,
        question,
        mode: 'research',
      });
    } catch (error) {
      denied = true;
      failure = error instanceof Error ? error.message : 'Unknown fail-closed error.';
    }

    report.negativeRun = {
      scenario: 'provider-unavailable',
      approvalDenied: denied,
      failure,
    };
    if (!denied) {
      throw new Error('Negative provider-failure case did not fail closed.');
    }

    report.status = 'PASS';
    report.reason = 'Live provider provenance, all NEXUS gates, and fail-closed negative proof passed.';
  } catch (error) {
    report.status = 'BLOCKED';
    report.reason = error instanceof Error ? error.message : 'Unknown SB-034 proof failure.';
    process.exitCode = 2;
  } finally {
    await persistReport();
    console.log(JSON.stringify(report, null, 2));
  }
}

await main();
