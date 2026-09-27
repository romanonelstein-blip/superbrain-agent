# SB-019 controlled experiments

SB-019 accepts only an improvement candidate whose source status is `PROPOSED`.
`ExperimentCandidate.from_improvement_candidate` preserves the SB-017 candidate
ID, lesson ID, confidence, description, and status.

Before execution, the engine creates an immutable content-addressed snapshot of:

- candidate metadata and artifacts;
- the exact Golden Task suite and suite digest;
- the accepted Golden baseline and baseline digest;
- the complete SB-018 promotion-policy thresholds and policy digest;
- the candidate executor identity;
- the creation timestamp.

Candidate artifacts are materialized read-only in a disposable private directory.
The candidate executor receives only frozen `GoldenTask` values and a bounded
`ExperimentSandbox` API for reading its own artifacts and writing relative-path,
size-limited output artifacts. It never receives the Golden Suite, baseline, or
promotion-policy objects. The disposable directory is removed after evaluation.
The engine rechecks the suite, baseline, and policy bytes before comparison.

## Persistence

`SQLiteExperimentStore` persists:

- immutable snapshot JSON and hashes;
- exact contract and candidate input artifacts;
- every candidate output artifact;
- the full baseline report, candidate report, and comparison report;
- an ordered event trace;
- creation, start, completion, or failure timestamps;
- the final experiment-only decision.

SQLite triggers prevent snapshot mutation, experiment deletion, artifact update or
deletion, event update or deletion, and any artifact/event append after an
experiment reaches `COMPLETED` or `FAILED`.

## Decisions

SB-018 promotion results map to exactly three SB-019 decisions:

- `REJECTED_REGRESSION` → `REJECT`
- `NO_PROMOTION` → `NO_IMPROVEMENT`
- `ELIGIBLE_FOR_EXPLICIT_APPROVAL` → `ELIGIBLE_FOR_APPROVAL`

All records enforce `automatic_change_applied = 0`. The engine contains no apply,
merge, commit, push, deploy, routing update, prompt update, or live-behavior update
method.

Run the deterministic acceptance experiment:

```text
python -m nexus1000.sb019_experiment
```

## Isolation boundary

This is a controlled application-level sandbox for trusted experiment executors:
frozen inputs, hidden contracts, bounded artifact APIs, disposable storage,
post-run contract verification, and append-only audit persistence. It is not an
adversarial operating-system container. Arbitrary untrusted native/Python code
would additionally require a separate OS sandbox, process capability restrictions,
network isolation, and resource limits.
