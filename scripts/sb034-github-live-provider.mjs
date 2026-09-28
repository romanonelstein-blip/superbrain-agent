import { createHash } from 'node:crypto';

const owner = 'romanonelstein-blip';
const repo = 'superbrain-agent';
const sha = process.env.SUPERBRAIN_PROOF_SHA?.trim() || process.env.GITHUB_SHA?.trim();

function hash(buffer) {
  return `sha256:${createHash('sha256').update(buffer).digest('hex')}`;
}

async function fetchBytes(url, accept = '*/*') {
  const response = await fetch(url, {
    headers: {
      Accept: accept,
      'User-Agent': 'SuperBrain-SB034-Live-Proof/1.0',
    },
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
    configuredProviders: [
      'github-rest-live',
      'github-raw-live',
      'github-proof-contract-live',
    ],
  };
}

async function collect(request) {
  if (!sha) throw new Error('SUPERBRAIN_PROOF_SHA is required for live evidence collection.');
  if (!request.question?.trim()) throw new Error('A proof question is required.');

  const commitUrl = `https://api.github.com/repos/${owner}/${repo}/commits/${sha}`;
  const packageUrl = `https://raw.githubusercontent.com/${owner}/${repo}/${sha}/package.json`;
  const proofUrl = `https://raw.githubusercontent.com/${owner}/${repo}/${sha}/docs/SB-034-PROOF.md`;

  const [commitSource, packageSource, proofSource] = await Promise.all([
    fetchBytes(commitUrl, 'application/vnd.github+json'),
    fetchBytes(packageUrl, 'text/plain'),
    fetchBytes(proofUrl, 'text/plain'),
  ]);

  const commit = JSON.parse(commitSource.text);
  const pkg = JSON.parse(packageSource.text);
  if (commit.sha !== sha) throw new Error('GitHub returned a different commit SHA than requested.');
  if (pkg.name !== 'superbrain-agent') throw new Error('Live package manifest identity check failed.');
  if (!proofSource.text.includes('grand_council') || !proofSource.text.includes('verifier')) {
    throw new Error('Live SB-034 proof contract is missing required gate names.');
  }

  const retrievedAt = new Date().toISOString();
  const requestId = request.runId || `sb034-${sha.slice(0, 12)}`;

  return {
    protocolVersion: 1,
    evidence: [
      {
        id: `github-commit-${sha.slice(0, 16)}`,
        claim: `GitHub REST confirms exact proof commit ${sha} exists for ${owner}/${repo}.`,
        stance: 'support',
        sourceId: commitUrl,
        sourceFamily: 'api.github.com',
        reliability: 0.95,
        freshness: 1,
        relevance: 1,
        verified: true,
        citation: commitUrl,
        contentHash: hash(commitSource.bytes),
        retrievedAt,
        contentType: 'application/json',
        provider: 'github-rest-live',
        providerRequestId: requestId,
        providerAttempts: 1,
      },
      {
        id: `github-package-${sha.slice(0, 16)}`,
        claim: `The live package manifest identifies ${pkg.name} version ${pkg.version}.`,
        stance: 'support',
        sourceId: packageUrl,
        sourceFamily: 'raw.githubusercontent.com',
        reliability: 0.9,
        freshness: 1,
        relevance: 1,
        verified: true,
        citation: packageUrl,
        contentHash: hash(packageSource.bytes),
        retrievedAt,
        contentType: 'application/json',
        provider: 'github-raw-live',
        providerRequestId: requestId,
        providerAttempts: 1,
      },
    ],
    dissent: {
      completed: true,
      provider: 'github-proof-contract-live',
      requestId: `${requestId}-dissent`,
      evidence: [
        {
          id: `github-proof-contract-${sha.slice(0, 16)}`,
          claim: 'The live SB-034 proof contract challenges approval unless every canonical gate and a fail-closed negative case are evidenced on the exact tested SHA.',
          stance: 'challenge',
          sourceId: proofUrl,
          sourceFamily: 'github-proof-contract',
          reliability: 0.9,
          freshness: 1,
          relevance: 1,
          verified: true,
          citation: proofUrl,
          contentHash: hash(proofSource.bytes),
          retrievedAt,
          contentType: 'text/plain',
          provider: 'github-proof-contract-live',
          providerRequestId: `${requestId}-dissent`,
          providerAttempts: 1,
        },
      ],
    },
    audit: [
      {
        stage: 'live_provider',
        detail: `Fetched exact commit, package manifest, and proof contract for ${sha}.`,
      },
    ],
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
