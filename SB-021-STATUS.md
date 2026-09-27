# SB-021 Provider Resilience — implementation status

## Status

SB-021 source implementation is present and the platform-independent gates available in this
Linux workspace pass. A full Vitest run is not claimed here because the uploaded ZIP bundled
Windows-native Node dependencies and the offline Linux environment does not contain the matching
`@esbuild/linux-x64` package. No real provider credentials were present and no live provider call
was attempted.

## Implemented controls

- bounded retries for transient provider failures;
- no retry for terminal auth/bad-request/invalid-response failures;
- failover across configured providers;
- provider allowlist and model allowlist;
- router-level execution timeout;
- total attempt, total latency and deterministic cost-unit budgets;
- local circuit breaker with cooldown;
- local per-provider rate limiting;
- explicit failure taxonomy;
- credential-safe error sanitization;
- resilience metadata on successful provider execution;
- environment-driven production policy controls;
- deterministic SB-021 self-test;
- opt-in live-provider smoke runner that safely reports `skipped` unless explicitly enabled.

## Verified in this workspace

- Python regression suite: **182/182 passed**.
- Python compile/import gate: **passed**.
- TypeScript full-project typecheck via the TypeScript compiler: **passed**.
- TypeScript compilation/build via the TypeScript compiler: **passed**.
- SB-021 deterministic runtime self-test: **passed**.
- Credential-pattern scan: **0 matches**.
- Live smoke with no opt-in: **safely skipped**.

## Not claimed

- Full Vitest suite was not executed in this Linux container because the uploaded npm dependency
  cache contains Windows-native binaries and no network access is available to fetch the Linux
  optional esbuild package.
- No OpenAI, Anthropic or Gemini provider is marked live-validated by this report.
- No deployment, push, merge or production rollout was performed.

## Changed source/configuration

- `integrations/superbrain_orchestrator_v2/src/providers/resilience.ts` (new)
- `integrations/superbrain_orchestrator_v2/src/providers/router.ts`
- `integrations/superbrain_orchestrator_v2/src/providers/factory.ts`
- `integrations/superbrain_orchestrator_v2/src/providers/index.ts`
- `integrations/superbrain_orchestrator_v2/src/types.ts`
- `integrations/superbrain_orchestrator_v2/src/sb021-selftest.ts` (new)
- `integrations/superbrain_orchestrator_v2/src/sb021-live-smoke.ts` (new)
- `integrations/superbrain_orchestrator_v2/tests/provider-resilience.test.ts` (new)
- `integrations/superbrain_orchestrator_v2/package.json`
- `integrations/superbrain_orchestrator_v2/.env.example`
- `.github/workflows/sb018-quality.yml`
- `README.md`
- `SUPERBRAIN-INTEGRATION.md`

## Final verification still required

On a native Windows workspace or GitHub Actions runner with dependencies restored through `npm ci`:

```text
npm test
npm run typecheck
npm run build:bridge
npm run sb021:selftest
```

Real provider smoke is separate and must only be enabled intentionally with valid credentials.
