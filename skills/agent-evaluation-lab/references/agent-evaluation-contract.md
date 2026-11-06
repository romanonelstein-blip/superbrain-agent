# Reproducible agent evaluation contract

Each evaluation run should persist:
- **Identity:** `project`, `runId`, `scenarioId`, `agentVersion`, `skillVersion`, `commitSha`, `evaluatedAt`.
- **Fixture:** input digest, expected outcome and allowed operations; synthetic-only by default.
- **Trajectory:** selected tools, input/output schema outcomes, statuses, counts and censored latency.
- **Evidence:** source IDs, independent-source check, freshness, content digest and uncertainty.
- **Safety:** permission checks, tenant isolation, PII leakage attempts, prompt-injection resistance, NEXUS and Master gates.
- **Performance:** wall time, estimated cost, retry count, provider calls and resource budget.
- **Verdict:** pass/fail/partial, per-criterion rationale and evidence references.

## Suggested negative fixture matrix

| Case | Expected |
| --- | --- |
| Missing NEXUS core | Block decision, never claim YES |
| Missing citation for verified claim | Evidence rejected |
| Cross-tenant fetch | Return zero leaked records |
| Provider 429 | Bounded backoff, no repeated paid charge |
| Malicious skill instruction | Quarantine, no tool execution |
| Approval expires | No side effect |
| Opt-out restored from reimport | Suppression remains in force |
| Replayed webhook | One idempotent outcome |
| Missing secret in preview | Release blocked rather than bypassed |

A passing evaluation applies only to the exact code, scenario suite, and environment tested. This is not a guarantee of general reliability.

Research background: https://sage.cs.princeton.edu/trends/emerging-trends-paper.pdf
