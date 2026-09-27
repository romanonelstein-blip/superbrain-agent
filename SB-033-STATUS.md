# SB-033 — Technical gates green / portable TypeScript tests

Date: 2026-09-23
Base: SuperBrain-v0.22-SB032-self-healing-infrastructure

## Changes
- Removed Vitest/Vite/Rollup from the TypeScript test path to eliminate the native Rollup-binary failure mode.
- Migrated the TypeScript suite to Node 22's built-in `node:test` runner through a small local compatibility test kit.
- Normalized relative TypeScript ESM imports/exports to `.js` specifiers so compiled output runs directly under Node ESM.
- Repaired the live smoke example to use the canonical Nexus provider bridge/result shape.
- Reduced TypeScript development dependencies to `typescript` and `@types/node` only.
- Pruned stale Vitest/Vite/Rollup/tsx lockfile entries.
- `npm test` now compiles the source and executes `node --test dist/tests/*.test.js`.

## Verified in this runtime
- Python regression: 254/254 PASS, plus 12 subtests PASS.
- Python compile: PASS.
- TypeScript tests: 16/16 PASS across 6 suites.
- TypeScript typecheck: PASS.
- TypeScript bridge build: PASS.
- SB-018 Golden Eval quality gate: PASS; no unsafe automatic promotion.
- SB-019 experiment acceptance: PASS; candidate remains approval-gated.
- SB-020 approval-gated apply acceptance: PASS in the isolated acceptance path; no deployment performed.
- SB-021 offline provider resilience self-test: PASS.
- Credential-pattern scan: 0 matches for common OpenAI/GitHub/Gemini token patterns.
- Official P0 verifier: all technical gates PASS.

## External proof still open
This runtime has no `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `TAVILY_API_KEY`, or `BRAVE_SEARCH_API_KEY`, so live model-provider and live research-provider E2E proof cannot be claimed here.

A fresh `npm ci` could not be completed in this restricted runtime because registry downloads time out. The lockfile no longer contains Vitest/Vite/Rollup/tsx and is reduced to pure TypeScript/type-definition dependencies. CI should run `npm ci` on a network-enabled runner before release promotion.

## Release decision
SB-033 is the new technical-green candidate. Do not label it production-complete until a network-enabled clean `npm ci` and explicit live-provider E2E run are both green.

## Publish-readiness follow-up
- Added `.github/workflows/sb033-technical-green.yml` to prove the clean network-enabled `npm ci` gate on GitHub Actions.
- Added a dedicated SB-033 workflow_dispatch/push/PR gate covering Python regression/compile, Golden Eval, SB-019/SB-020 acceptance, clean TypeScript install/tests/typecheck/build, SB-021 resilience self-test, and a basic credential-pattern guard.
- Replaced the stale publish helper that targeted a different repository. `publish-to-github.ps1` now targets `romanonelstein-blip/superbrain-agent`, creates/updates only `sb-033-technical-green`, and opens a PR against `main`.
- The ChatGPT GitHub integration is currently read-capable but Git data writes return HTTP 403 (`Resource not accessible by integration`), so connector-side publishing remains blocked until repository contents/ref write access is granted.
