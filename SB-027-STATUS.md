# SB-027 — World Model + Live OSINT Diagnostics

Status: **COMPLETE in the packaged local runtime.**

## Added

- `nexus1000/world_model.py`
  - persistent evidence-weighted belief ledger;
  - deterministic confidence and state revision;
  - states: `UNKNOWN`, `SUPPORTED`, `CONTESTED`, `REFUTED`, `UNCERTAIN`;
  - cumulative support/challenge strength;
  - unique source/source-family counts;
  - freshness and revision tracking;
  - novel-evidence deduplication across missions.
- SQLite migration for `world_beliefs` and `world_belief_evidence`.
- Automatic World Model revision after evidence/provider/research/deep-research missions.
- World Model state included in selected Mission Detail and `GET /api/world-model`.
- `POST /api/osint/diagnostics` for live GitHub + DuckDuckGo + guarded retrieval checks.
- Local Tor detection and Tor Project status validation when a local SOCKS endpoint is available.
- Controlled DuckDuckGo onion diagnostic through a temporary explicit allowlist; production onion policy remains closed by default.
- Mission Control World Model and live OSINT panels.

## Canonical chain

`Mission → Research/Provider evidence → guarded retrieval → Evidence → NexusOrchestrator → World Model revision → persistence`

The World Model does **not** become a second final-decision engine. `NexusOrchestrator` remains the canonical final judge.

## Safety boundary

- No automatic code changes, prompt mutation, merge, push or deployment.
- World Model never promotes memory to fresh proof.
- Quarantined evidence is excluded from belief revision.
- OSINT diagnostics never return credential values or response bodies.
- Arbitrary onion discovery remains disabled.
- Production onion retrieval still requires Tor mode plus an explicit allowlist.
- Stealth remains local loopback isolation/privacy, not a guarantee of universal anonymity or invisibility.

## Verification

- Full Python suite: **236/236 passed**.
- SB-027 targeted tests: **4/4 passed**.
- Python compile gate: passed.
- Mission Control JavaScript syntax check: passed.
- Deterministic SB-027 acceptance mission: passed; repeated evidence moved the persistent belief from `SUPPORTED` to `CONTESTED` while Nexus remained the only final judge.
- Live OSINT diagnostic path executed in the packaging environment. GitHub and DuckDuckGo could not resolve externally because the packaging environment has no outbound DNS/network, and the diagnostic correctly surfaced this as provider failure rather than claiming live validation.


## SB-027.1 launcher fix

The Windows live OSINT launcher now uses an absolute script path and detects
the common ZIP-preview execution case. If the sibling Python test is not
materialized, it attempts to recover the latest downloaded SB-027 ZIP into a
temporary directory and runs the packaged smoke test from there.

Validation after the launcher-only change:

- Python tests: 236/236 passed
- SB-027 subtests: 12/12 passed
- Python compile gate: passed
- SB-027 acceptance mission: passed
