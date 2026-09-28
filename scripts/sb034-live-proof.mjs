const requiredGates = ['grand_council', 'neis', 'blinded_dissent', 'verifier'];

const commandMode = Boolean(process.env.SUPERBRAIN_EVIDENCE_PROVIDER_COMMAND?.trim());
const primary = process.env.SUPERBRAIN_RESEARCH_PRIMARY_ENDPOINT?.trim();
const dissent = process.env.SUPERBRAIN_RESEARCH_DISSENT_ENDPOINT?.trim();
const httpMode = Boolean(primary && dissent);
const partialHttpMode = Boolean(primary || dissent) && !httpMode;
const mixedMode = commandMode && Boolean(primary || dissent);

const sha = process.env.GITHUB_SHA?.trim() || process.env.SUPERBRAIN_PROOF_SHA?.trim() || 'unknown';
const report = {
  protocol: 'SB-034-live-proof-v1',
  sha,
  requiredGates,
  providerMode: commandMode ? 'command' : httpMode ? 'http-research' : 'unconfigured',
  status: 'BLOCKED',
  reason: '',
};

if (mixedMode) {
  report.reason = 'Command and HTTP evidence modes cannot be configured together.';
} else if (partialHttpMode) {
  report.reason = 'HTTP research proof requires both primary and dissent endpoints.';
} else if (!commandMode && !httpMode) {
  report.reason = 'No live evidence provider is configured.';
} else if (sha === 'unknown') {
  report.reason = 'Exact tested Git SHA is required for SB-034 proof.';
} else {
  report.status = 'READY_FOR_LIVE_EXECUTION';
  report.reason = 'Provider configuration preflight passed. This is not a live-run PASS.';
}

console.log(JSON.stringify(report, null, 2));

// SB-034 never converts configuration readiness into a live proof PASS.
// A later runtime step must execute the provider and NEXUS chain and record all required gates.
if (report.status !== 'READY_FOR_LIVE_EXECUTION') process.exitCode = 2;
