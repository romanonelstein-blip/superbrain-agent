# SB-034 process recovery continuation — 2026-09-27

## Implemented outcome
A real child process now terminates abruptly with os._exit(73) inside a workflow
handler. A new process resumes through NexusOrchestrator.run_durable_workflow.
Completed checkpointed steps are not replayed; the interrupted step is retried.

The repeated-crash test exposed a defect: DurableWorkflow granted max_attempts
again on every run despite persisting the attempt count. Three forced exits
followed by resume incorrectly executed a fourth attempt and completed.
The regression test failed before the fix and passes after it.

The retry loop now uses the remaining persisted budget. An exhausted step is
saved as failed without another handler invocation. This intentionally applies
the configured maximum across restarts. Starting a new run is required for a
fresh budget; completed steps remain idempotent.

## Fresh verification
- Two subprocess recovery tests: PASS.
- Complete Python unittest discovery: 264 tests, 0 failures, PASS (6.453 seconds).
- Python compileall for nexus1000 and tests: PASS, exit 0.
- SB-018 Golden Eval: exit 0; current candidate accuracy 1.0, synthetic regression rejected.
- Existing SQLite backup/restore test: PASS within the full regression suite.
- No TypeScript source changed; TypeScript gates were not rerun this turn.

## Evidence boundaries
This is real abrupt process termination, not a raised Python exception.
It validates the canonical orchestrator's durable workflow seam with local
deterministic handlers. It does not establish live-provider E2E, external
side-effect exactly-once semantics, scheduler in-flight mission recovery,
machine power-loss durability, or automatic OS-level process restart.
An interrupted handler may run again: external writes still need their own
idempotency mechanism.

The source was the current SB-034 handoff archive, which has no Git metadata.
No remote reconciliation, commit, push, PR, merge, or deployment was performed.
Live-provider and full Nexus E2E remain unverified.
The prior verification report records historical evidence from the earlier turn.

## Changed files
- nexus1000/durable.py
- tests/test_v044_process_recovery.py
- CODEX-SB034-HANDOFF.md (continuation pointer)
- SB-034-PROCESS-RECOVERY-2026-09-27.md (this report)

NexusOrchestrator remains canonical. Automatic change application is unchanged.

**SB-034 NOT YET PRODUCTION VERIFIED**

## Follow-up — mixed failures and cross-platform CI

Added a third real-process regression: one abrupt crash followed by retryable
provider-like errors must consume only the remaining two attempts. A further
fresh process must stay failed even when its handler could succeed. The original
error and completed-step idempotency are preserved.

Added an independent process-recovery job to sb034-hermetic-ci.yml:
Ubuntu and Windows, Python 3.13, five-minute job timeout, no provider credentials.
Both operating systems run the three abrupt-exit tests plus the three existing
SQLite backup and scheduler persistence tests. Fail-fast is disabled so both
platform outcomes remain visible. This configuration does not itself enforce
GitHub branch protection and has not been run remotely.

Fresh local evidence:
- Process recovery: 3/3 PASS.
- SQLite backup and scheduler persistence: 3/3 PASS.
- Full Python regression: 265/265 PASS.
- Workflow YAML parses and includes both matrix targets.
- Windows execution and GitHub Actions execution: NOT RUN.
- TypeScript and live-provider gates: not rerun; unchanged.

Changed this follow-up: tests/test_v044_process_recovery.py,
.github/workflows/sb034-hermetic-ci.yml, this report, and handoff pointer.
No runtime code changes were needed for the mixed-failure scenario.
