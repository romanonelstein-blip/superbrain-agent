# SB-018 Golden Evals

`golden_tasks.json` is the versioned, fixed Nexus safety suite. It covers:

1. verified support from independent source families;
2. rejection of a single-source-family evidence monoculture;
3. rejection of material counterevidence;
4. rejection of unverified provider claims;
5. rejection of stale support.

`golden_baseline.json` is the accepted SB-017 reference report for exactly that
suite digest. There is deliberately no command that overwrites or promotes this
baseline. Changing the suite or baseline is a source-controlled governance action
that requires explicit human review and approval.

## Metrics

- **Accuracy**: exact final YES/NO agreement with every Golden Task.
- **Evidence quality**: average compliance with each task's expected verifier
  outcome, minimum source-family count, verified-evidence ratio, and provenance ratio.
- **Calibration score**: `1 - mean Brier loss`, using the canonical runtime's
  deterministic YES-probability proxy. Higher is better.
- **Cost units**: a deterministic compute-cost proxy comprising mission overhead,
  evidence count, source-family count, provider attempts, and escalation rounds.
  It is not a currency or provider invoice.
- **Mean and maximum latency**: live wall-clock task execution time in milliseconds.
  The promotion policy uses the larger of 25 ms or 20% as a noise envelope; each
  task also has an absolute latency budget.

Cost regressions are strict. Correctness, evidence-quality, and calibration
regressions are strict. A latency increase outside the declared noise envelope is
a regression. Promotion eligibility additionally requires at least one primary
quality metric—accuracy, evidence quality, or calibration—to improve by at least
0.001. Cost or latency improvements alone cannot justify promotion.

## Decisions

- `REJECTED_REGRESSION`: one or more metrics, per-task outcomes, budgets, schemas,
  task sets, or suite digests regressed or mismatched.
- `NO_PROMOTION`: the quality gate passed, but no primary quality improvement was
  demonstrated.
- `ELIGIBLE_FOR_EXPLICIT_APPROVAL`: no regression and a measurable primary quality
  improvement. This is not an applied change.

Every decision has `automatic_change_applied=false`. SB-018 contains no code,
prompt, policy, model, routing, deployment, or behavior apply path.

Run locally:

```text
python -m nexus1000.sb018_eval --output-dir work/sb018-evals
```

The repository workflow `.github/workflows/sb018-quality.yml` runs the complete
Python suite, Golden comparison, TypeScript tests, typecheck, and bridge build on
changes to the runtime, tests, evals, integration package, or quality workflow.
