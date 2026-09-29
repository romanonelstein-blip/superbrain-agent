import { createHash } from 'node:crypto';

const owner = 'romanonelstein-blip';
const repo = 'superbrain-agent';
const repositoryTrustBoundary = `github:${owner}/${repo}`;
const npmTrustBoundary = 'npm:registry.npmjs.org';
const sha = process.env.SUPERBRAIN_PROOF_SHA?.trim() || process.env.GITHUB_SHA?.trim();

function hash(buffer) {
  return `sha256:${createHash('sha256').update(buffer).digest('hex')}`;
}

async function fetchBytes(url, accept = '*/*') {
  const response = await fetch(url, {
    headers: { Accept: accept, 'User-Agent': 'SuperBrain-SB034-Live-Proof/1.0' },
    redirect: 'error',
  });
  if (!response.ok) throw new Error(`Live GitHub source returned HTTP ${response.status}.`);
  const bytes = Buffer.from(await response.arrayBuffer());
  if (bytes.length === 0) throw new Error('Live GitHub source returned empty content.');
  return { bytes, text: bytes.toString('utf8') };
}

async function liveStatus() {
  const url = `https://api.github.com/repos/${owner}/${repo}`;
  await fetchBytes(url, 'application/vnd.github+json');
  return {
    protocolVersion: 1,
    ready: true,
    interactiveMissionsAvailable: true,
    researchMissionsAvailable: true,
    configuredProviders: ['github-rest-live', 'github-raw-live', 'npm-registry-live'],
  };
}

async function collect(request) {
  if (!sha) throw new Error('SUPERBRAIN_PROOF_SHA is required for live evidence collection.');
  if (!request.question?.trim()) throw new Error('A proof question is required.');

  const commitUrl = `https://api.github.com/repos/${owner}/${repo}/commits/${sha}`;
  const packageUrl = `https://raw.githubusercontent.com/${owner}/${repo}/${sha}/package.json`;
  const lockUrl = `https://raw.githubusercontent.com/${owner}/${repo}/${sha}/package-lock.json`;
  const proofUrl = `https://raw.githubusercontent.com/${owner}/${repo}/${sha}/docs/SB-034-PROOF.md`;
  const [commitSource, packageSource, lockSource, proofSource] = await Promise.all([
    fetchBytes(commitUrl, 'application/vnd.github+json'),
    fetchBytes(packageUrl, 'text/plain'),
    fetchBytes(lockUrl, 'text/plain'),
    fetchBytes(proofUrl, 'text/plain'),
  ]);

  const commit = JSON.parse(commitSource.text);
  const pkg = JSON.parse(packageSource.text);
  const lock = JSON.parse(lockSource.text);
  if (commit.sha !== sha) throw new Error('GitHub returned a different commit SHA than requested.');
  if (pkg.name !== 'superbrain-agent') throw new Error('Live package manifest identity check failed.');
  if (!proofSource.text.includes('grand_council') || !proofSource.text.includes('verifier')) {
    throw new Error('Live SB-034 proof contract is missing required gate names.');
  }

  const lockedExeca = lock?.packages?.['node_modules/execa'];
  if (!lockedExeca?.version || !lockedExeca?.integrity) {
    throw new Error('Exact proof lockfile is missing execa version/integrity metadata.');
  }
  const npmMetadataUrl = `https://registry.npmjs.org/execa/${encodeURIComponent(lockedExeca.version)}`;
  const npmSource = await fetchBytes(npmMetadataUrl, 'application/json');
  const npmMetadata = JSON.parse(npmSource.text);
  if (npmMetadata.name !== 'execa' || npmMetadata.version !== lockedExeca.version) {
    throw new Error('Independent npm registry returned unexpected package metadata.');
  }
  if (npmMetadata.dist?.integrity !== lockedExeca.integrity) {
    throw new Error('Independent npm registry integrity does not match the exact proof lockfile.');
  }

  const retrievedAt = new Date().toISOString();
  const requestId = request.runId || `sb034-${sha.slice(0, 12)}`;
  const common = { trustBoundary: repositoryTrustBoundary, retrievedAt };

  return {
    protocolVersion: 1,
    evidence: [
      {
        ...common,
        id: `github-commit-${sha.slice(0, 16)}`,
        claim: `GitHub REST confirms exact proof commit ${sha} exists for ${owner}/${repo}.`,
        stance: 'support', sourceId: commitUrl, sourceFamily: 'api.github.com', reliability: 0.95,
        freshness: 1, relevance: 1, verified: true, citation: commitUrl,
        contentHash: hash(commitSource.bytes), contentType: 'application/json',
        provider: 'github-rest-live', providerRequestId: requestId, providerAttempts: 1,
      },
      {
        ...common,
        id: `github-package-${sha.slice(0, 16)}`,
        claim: `The live package manifest identifies ${pkg.name} version ${pkg.version}.`,
        stance: 'support', sourceId: packageUrl, sourceFamily: 'raw.githubusercontent.com', reliability: 0.9,
        freshness: 1, relevance: 1, verified: true, citation: packageUrl,
        contentHash: hash(packageSource.bytes), contentType: 'application/json',
        provider: 'github-raw-live', providerRequestId: requestId, providerAttempts: 1,
      },
    ],
    dissent: {
      completed: true,
      provider: 'npm-registry-live',
      requestId: `${requestId}-dissent`,
      evidence: [
        {
          trustBoundary: npmTrustBoundary,
          retrievedAt,
          id: `npm-execa-${lockedExeca.version.replace(/[^a-zA-Z0-9.-]/g, '-')}`,
          claim: `Independent npm registry metadata confirms locked dependency execa@${lockedExeca.version} and its integrity for the exact proof commit, challenging approval based only on repository-controlled evidence.`,
          stance: 'challenge', sourceId: npmMetadataUrl, sourceFamily: 'registry.npmjs.org', reliability: 0.95,
          freshness: 1, relevance: 1, verified: true, citation: npmMetadataUrl,
          contentHash: hash(npmSource.bytes), contentType: 'application/json',
          provider: 'npm-registry-live', providerRequestId: `${requestId}-dissent`, providerAttempts: 1,
        },
      ],
    },
    audit: [{ stage: 'live_provider', detail: `Fetched exact commit/package/proof contract for ${sha} and independently cross-checked locked execa@${lockedExeca.version} against npm registry integrity.` }],
    verificationNote: `Live GitHub provenance collected for exact SHA ${sha}.`,
  };
}

const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const raw = Buffer.concat(chunks).toString('utf8').trim();
const request = raw ? JSON.parse(raw) : {};
const result = request.type === 'status'
  ? await liveStatus()
  : request.type === 'collect'
    ? await collect(request)
    : (() => { throw new Error('Unsupported evidence provider request type.'); })();
process.stdout.write(JSON.stringify(result));
