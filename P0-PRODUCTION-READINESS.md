# SuperBrain SB-031 P0 durability patch

Date: 2026-09-22

## Implemented
- Persistent scheduler job state in SQLite.
- Restart-safe next-run state.
- Failure state persistence and bounded exponential backoff.
- SQLite online backup with integrity check.
- SQLite restore with pre-restore and post-restore integrity validation.
- CLI scheduler entrypoint.
- Three P0 durability tests.

## Verification
- Targeted durability tests: 3/3 passed.
- Full Python regression: 250/250 passed.
- Python compileall: passed.

## Still not proven in this environment
- Live external model-provider E2E validation: no OPENAI_API_KEY, ANTHROPIC_API_KEY or GEMINI_API_KEY is configured.
- Live research-provider validation: no TAVILY_API_KEY or BRAVE_SEARCH_API_KEY is configured.
- TypeScript test/typecheck re-run requires npm dependencies. The source archive intentionally does not contain node_modules, and dependency installation could not be completed in this restricted runtime.

## P0 decision
Durable scheduler + DB backup/restore: PASS.
Python regression/compile: PASS.
Live-provider production proof: OPEN.
Fresh TypeScript dependency/install/test proof in this runtime: OPEN.

## One-command P0 verification

Windows:

```bat
verify-p0.bat
```

After configuring live provider credentials:

```bat
verify-p0.bat --live
```

The verifier runs the Python regression and compile gates, installs npm dependencies when needed,
runs TypeScript tests/typecheck/build, reports configured provider credentials, and only performs
external provider smoke tests when `--live` is explicitly supplied.

## SB-033 follow-up (2026-09-23)
The Vitest/Rollup portability blocker was removed. TypeScript tests now use Node's built-in test runner; 16/16 tests, typecheck, and bridge build pass in the SB-033 candidate. Python regression is 254/254 plus 12 subtests. Remaining release evidence is a network-enabled clean `npm ci` and live external-provider E2E with configured credentials. See `SB-033-STATUS.md`.
