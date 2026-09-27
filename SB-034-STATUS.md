# SB-034 — Hermetic CI Candidate

Date: 2026-09-24
Base: SB-033 Publish Ready

## Change
Only `tests/test_v016_provider_integration.py` was changed.

Two subprocess test commands now invoke Python with `-S`:
- `python -c ...` -> `python -S -c ...`

This prevents environment-level `sitecustomize` / startup hooks from polluting deterministic subprocess test output.
No Nexus decision logic, provider routing, persistence, recovery, security, or production runtime code was changed.

## Verified in current runtime
- Python regression suite: 254/254 PASS
- Compiled TypeScript Node tests: 16/16 PASS
- Python hermetic subprocess regression: PASS

## Evidence boundary
A fresh `npm ci` could not be completed in the current environment because npm registry access is unavailable/hanging.
Therefore the clean-install TypeScript source gates (`npm test`, `npm run typecheck`, `npm run build:bridge`) still require a network-enabled CI runner such as GitHub Actions.

SB-034 is a CI/reproducibility candidate, not yet a production promotion.


## CI hardening added
- Replaced the SB-033 branch workflow with `.github/workflows/sb034-hermetic-ci.yml`.
- Candidate branch target: `sb-034-hermetic-ci`.
- Added `.github/workflows/sb034-live-provider.yml`.
- Live provider gate is manual and requires at least one configured provider secret.
- A live smoke that reports `skipped` is treated as failure for production promotion.
- `main` is not a direct push target for the candidate workflow.
