# Codex Handoff — SuperBrain SB-034

Latest continuation: read SB-034-PROCESS-RECOVERY-2026-09-27.md.
Real subprocess crash recovery is tested; persisted retry budget defect fixed.
Python: 265/265. Three process recovery tests; Windows/Linux CI job added.
Windows execution, live E2E and remote publication remain open.

## Continuation update — 2026-09-27

Read `SB-034-VERIFICATION-2026-09-27.md` first. Clean dependency installation now
passes in the current runtime; Python is 262/262 and TypeScript is 16/16.
The live-provider gate now validates structured attempted/successful results.
Live provider and full Nexus E2E proof remain open. The historical baseline and
required remote execution sequence below have not been represented as completed.

## Objective
Continue from the existing SB-034 hardened candidate. Do not rebuild earlier milestones.

Repository:
`romanonelstein-blip/superbrain-agent`

Target branch:
`sb-034-hermetic-ci`

Do not modify `main` directly.

## Current verified local state
- Python regression: 254/254 PASS
- Compiled TypeScript tests: 16/16 PASS
- Secret-pattern scan: 0 matches
- Hermetic subprocess fix: PASS
- SB-033 remains the previous rollback baseline

## Required execution sequence

1. Verify repository/remotes and current branch.
2. Use the SB-034 candidate as the source of truth.
3. Create or update branch `sb-034-hermetic-ci`.
4. Commit only the intended SB-034 changes.
5. Push the branch.
6. Run `.github/workflows/sb034-hermetic-ci.yml`.
7. Require a real clean `npm ci`.
8. Require all Python, TypeScript, typecheck, build, Golden Eval, SB-019, SB-020, SB-021, resilience, recovery and secret/security gates to PASS.
9. If any gate fails:
   - determine root cause;
   - apply the smallest justified fix;
   - add/update regression coverage where appropriate;
   - commit and push;
   - rerun CI;
   - continue until green.
10. Run `.github/workflows/sb034-live-provider.yml`.
11. Do not treat skipped live-provider tests as PASS.
12. Use only existing secure GitHub secrets; never print or commit credentials.
13. Verify at least one genuine external provider call if credentials exist.
14. Verify crash→resume and backup→restore paths.
15. Open a PR from `sb-034-hermetic-ci` to `main`.
16. Merge only if every required P0 gate and at least one true live-provider E2E are green.
17. Preserve SB-033 as the rollback baseline.

## Absolute rules
- NexusOrchestrator remains the canonical final-decision engine.
- Do not create a second orchestrator.
- Do not remove or weaken tests just to get CI green.
- Do not use fixtures/mocks as proof of live-provider E2E.
- Do not force-push `main`.
- `automatic_change_application = false`.
- Do not claim production verification without executed evidence.

## Final report format

Return:

- commit SHA
- branch
- PR number/link
- `npm ci`: PASS/FAIL
- Python: exact passed/failed count
- TypeScript: exact passed/failed count
- typecheck: PASS/FAIL
- build: PASS/FAIL
- Golden Eval: PASS/FAIL
- SB-019: PASS/FAIL
- SB-020: PASS/FAIL
- SB-021: PASS/FAIL
- crash→resume: PASS/FAIL
- backup→restore: PASS/FAIL
- security/secrets: PASS/FAIL
- live-provider E2E: PASS/FAIL/BLOCKED
- changed files
- root cause of every encountered failure
- final status, exactly one of:

`SB-034 PRODUCTION VERIFIED`

or

`SB-034 NOT YET PRODUCTION VERIFIED`

Start executing immediately. Do not stop after inspection or planning if the next safe action can be performed.
