# SB-034 continuation — 2026-09-27

## Implemented

Hardened the live-provider acceptance boundary in the existing SB-034 candidate.
The GitHub workflow previously searched for text markers. Its completed-marker
check accepted `{"liveSmoke": "completed", "results": []}` even though that
report contained no attempted provider call. This was reproduced locally.

The new shared JSON validator requires a completed report, at least one result,
a supported external provider, a nonblank model, and literal boolean `true` for
both attempted and success on every result. Skipped, malformed, empty, mock,
partially failed and truthy-string reports fail. Invalid report contents are
not printed. The workflow retains pipefail to independently enforce the smoke
process's exit status.

The local P0 verifier now runs the bounded SB-021 smoke with explicit opt-in,
requires its successful process exit and validates its report with the same
validator. The process has a 90-second outer timeout. The existing GitHub/DDG
connectivity check is correctly labeled OSINT; it is not proof of Tavily/Brave
or of the complete canonical Nexus live pipeline.

## Fresh verification

| Gate | Result |
| --- | --- |
| Clean `npm ci --no-audit --no-fund --fetch-retries=0 --fetch-timeout=15000` | PASS, 3 packages installed |
| Python regression | PASS, 262 passed / 0 failed (254 existing + 8 new) |
| Compiled TypeScript tests | PASS, 16 passed / 0 failed |
| `npm run typecheck` | PASS |
| `npm run build:bridge` | PASS |
| Python compile | PASS |
| Golden Eval / SB-018 | PASS, 5/5 tasks; no automatic promotion |
| SB-019 acceptance | PASS, eligible for approval only |
| SB-020 isolated acceptance | PASS, no deployment |
| SB-021 offline resilience self-test | PASS |
| Scheduler recreation and persisted backoff | PASS, deterministic test |
| SQLite backup / restore roundtrip | PASS |
| Real forced-process-crash then resume | NOT EXECUTED; object recreation is not an OS crash |
| Common credential-pattern scan | 0 matching files; not a full security audit |
| Real Node smoke without credentials | Correctly reports skipped; both validator and local verifier reject it |
| Live model-provider call | BLOCKED, no configured model keys in this runtime |
| Full live research / Nexus E2E | NOT VERIFIED |

`python scripts/verify_p0.py --skip-install` was run after the successful clean
install. It exited 2 as designed: technical checks pass, live proof remains open.
No provider credentials were printed or packaged. No automatic runtime changes
or deployment were performed. NexusOrchestrator remains the canonical engine.

## Changed source files

- `scripts/validate_live_provider.py` (new)
- `tests/test_v043_live_provider_gate.py` (new)
- `scripts/verify_p0.py`
- `.github/workflows/sb034-live-provider.yml`

This report and the handoff addendum document the continuation.

## GitHub / release boundary

Repository metadata and the existence of `sb-034-hermetic-ci` were confirmed.
Fetching `scripts/verify_p0.py` and root `AGENTS.md` at that branch returned 404.
The local source of truth was the supplied v0.24 SB-034 handoff archive.
No remote source reconciliation, commit, push, PR, merge or GitHub Actions run
was performed. Commit SHA and PR: not created for these changes.

Next: reconcile the actual branch tree with this candidate, execute the updated
workflow in GitHub, run genuine provider and full Nexus E2E with securely
configured credentials, and perform a forced-crash recovery acceptance test.
Preserve SB-033 as the rollback baseline.

**SB-034 NOT YET PRODUCTION VERIFIED**
