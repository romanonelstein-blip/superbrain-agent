# Super Brain / NEXUS-1000 v0.17 integration

Canonical runtime: NEXUS-1000 v0.15 core.

Added:
- Superbrain Orchestrator v2 provider layer
- OpenAI / Anthropic / Gemini provider adapters
- provider routing and failover scaffold
- preserved NEXUS councils, evidence graph, verifier gates, policy/tool registry,
  durable workflows, distributed messaging, persistent + semantic memory

Integration policy:
1. Do not replace the proven NEXUS core.
2. Model providers feed specialist/council execution.
3. All claims/results continue through Evidence Graph.
4. Verifier remains release/decision gate.
5. Memory writes happen only after verifier-approved runs.
6. Future self-improvement must be versioned, test-gated, and reversible.

Implemented consolidation seam:
- `runNexusProviderMission` executes only provider-backed specialist work.
- The JSON CLI bridge preserves provider/model/request/agent provenance.
- `TypeScriptProviderBridge` imports that evidence into Python.
- `NexusOrchestrator.run_provider_mission` is the only final-decision path.
- Provider output is unverified by default and cannot silently bypass Nexus verification.
- Provider-supplied verification flags are ignored, including malformed or malicious `true` values.
- `SourceEvidenceEnricher` requires independently resolved source content, an exact cited passage,
  and a separate stance-aware support checker before creating verified evidence.
- Verified SUPPORT and verified CHALLENGE evidence use the same Evidence Graph and Grand Council path.
- `LocalDocumentResolver` provides the first real allowlisted retrieval path for registered local documents.
- Local retrieval blocks root escape, unknown IDs, unapproved types, invalid UTF-8, and oversized content.
- Citation text, SHA-256, retrieval timestamp, relative location, and content type persist with evidence.
- Existing v0.15 SQLite databases receive the new nullable provenance columns in place.
- Provider, model, request ID, agent, failover attempts, and latency persist with evidence.
- Verifier-approved YES runs can write semantic memory; rejected runs never do.
- `HttpsSourceResolver` validates an exact domain/port allowlist, public DNS answers,
  pinned-IP TLS, every redirect, size, timeout, compression, UTF-8, and media type.
- Attached SQLite persistence stores the final result, evidence, and timeline audit.

The old TypeScript `SuperbrainOrchestrator` name remains only as an internal deep-import
compatibility wrapper. It delegates directly to `runNexusProviderMission`, has no own
critic/verifier/synthesizer flow, and is not exported from the public API. Python Nexus
owns every final decision.

SB-016 verification entrypoint:
`python -m nexus1000.sb016_mission` runs a deterministic cross-language mission using
the real TypeScript ProviderRouter and failover path, source-backed evidence, every
Nexus gate, persistence, and verifier-gated semantic memory without external secrets.

SB-017 controlled-learning seam:
- `ControlledLearningLoop` runs only after Nexus has produced a final result and the verifier passed.
- The reflection context contains the mission, final value, gate outcomes, and non-quarantined evidence.
- Every stored lesson must reference verified evidence with citation and content-hash provenance.
- Lesson confidence cannot exceed the least reliable referenced evidence item.
- `SQLiteLearningStore` deduplicates lessons and candidates while preserving per-run evidence snapshots.
- Improvement candidates remain permanently `PROPOSED` in this milestone; no apply/execute path exists.
- Invalid reflection output fails explicitly and marks an attached operational run `reflection_failed`.

SB-017 verification entrypoint:
`python -m nexus1000.sb017_mission` extends the SB-016 cross-language mission through
reflection, lesson persistence, provenance verification, and proposal-only improvements.

SB-018 Golden Eval and promotion boundary:
- Five fixed safety tasks cover independent support, evidence monoculture,
  counterevidence, unverified claims, and stale evidence.
- Reports measure exact correctness, evidence-quality compliance, Brier-based
  calibration, deterministic cost units, and live mean/maximum latency.
- Candidate reports are comparable only when their suite ID, suite digest, task set,
  and report schema exactly match the accepted baseline.
- Correctness, evidence quality, calibration, and cost are fail-closed non-regression
  gates; latency has a documented noise envelope plus absolute per-task budgets.
- Promotion eligibility requires no regression and a measurable improvement in
  accuracy, evidence quality, or calibration. Equal metrics produce `NO_PROMOTION`.
- `ELIGIBLE_FOR_EXPLICIT_APPROVAL` is only a recommendation. No apply path exists,
  and every decision records `automatic_change_applied=false`.
- `.github/workflows/sb018-quality.yml` runs Golden Evals plus all Python and
  TypeScript gates whenever relevant paths change.

SB-018 verification entrypoint:
`python -m nexus1000.sb018_eval --output-dir work/sb018-evals` produces JSON and
Markdown comparisons for the current runtime and a deterministic rejected-regression example.

SB-019 controlled experiment boundary:
- Only SB-017 candidates with source status `PROPOSED` can enter an experiment.
- Candidate metadata, artifacts, source lesson/confidence, executor identity, Golden
  Suite, accepted baseline, and SB-018 thresholds are content-addressed before execution.
- Candidate execution receives frozen Golden Tasks and a bounded disposable sandbox;
  it does not receive the suite, baseline, or promotion-policy objects.
- The exact Golden, baseline, and policy contract is reverified before comparison.
- The append-only SQLite store retains full metrics, reports, artifacts, ordered
  events, timestamps, and failure state across reopen.
- Decisions map only to `REJECT`, `NO_IMPROVEMENT`, or `ELIGIBLE_FOR_APPROVAL`.
- Eligibility is not approval and cannot apply, merge, commit, push, deploy, or
  alter live behavior. Every record enforces `automatic_change_applied = 0`.

SB-019 verification entrypoint:
`python -m nexus1000.sb019_experiment` runs a calibration-only proposed candidate
through the exact Golden Suite and persists an eligible-for-approval result without
applying it.

## SB-020 approval-gated application

The canonical flow now has a deliberately separate human authority boundary:

```text
immutable eligible SB-019 experiment
  -> content-addressed HUMAN approval (HMAC-SHA256)
  -> exact experiment/snapshot/candidate/suite binding
  -> single-use consumption
  -> precondition verification + pre-apply snapshot
  -> bounded declarative atomic replacements
  -> unchanged Golden Eval suite
  -> commit, or automatic rollback + hash and Golden verification
  -> immutable audit trail
```

`ApprovalGatedApplyEngine` does not accept candidate code, commands, callbacks, deployments,
or approval generated by an AI/agent/service identity. Trusted Nexus code supplies the
post-apply evaluator. Apply plans can replace at most twenty existing, regular, non-symlink
files inside the explicitly selected workspace and must name immutable candidate artifacts
plus the exact pre-apply SHA-256 of every target.

The HMAC key is an external human-authority secret and is not stored in the approval or audit
database. Production use must obtain it from a human-controlled secret/signing service; the
acceptance CLI uses an isolated ephemeral demonstration key and workspace only.

## SB-021 provider resilience

The TypeScript provider bridge now treats external model execution as a failure-prone boundary.
`ProviderRouter` applies explicit provider/model allowlists, retry classification, circuit breaking,
local rate limiting, cost/attempt/latency budgets, router-level timeouts, and secret-safe failure
summaries before any provider output can continue into the existing source-backed Nexus evidence
pipeline. These controls do not bypass citation verification, the Verifier, or the Final Judge.

Deterministic validation is available through `npm run sb021:selftest`. Real-provider smoke tests
are separate and opt-in through `SUPERBRAIN_LIVE_PROVIDER_SMOKE=1`; missing credentials or missing
opt-in produce a safe `skipped` result rather than a false success claim.

## SB-022 — Mission Control integration boundary

`nexus1000.mission_control.MissionControlService` is a control-plane facade only. Final decisions
still delegate to `NexusOrchestrator.run_evidence_mission`. `nexus1000.sb022_server` exposes the
facade over a small stdlib HTTP server and static UI without adding a second orchestration path.

Durable Master review is append-only in `master_decisions`. `ACCEPT`, `MODIFY`, `RESEARCH_MORE`,
`OVERRIDE`, and `REJECT` express human authority over what happens next, but never mutate the
historical Nexus `FinalDecision`. This preserves both the machine decision and the human decision
for later outcome analysis.

Mission Control intentionally does not claim that arbitrary user-entered claims are independently
verified. Verified evidence submitted to the API must already carry citation and content-hash
provenance. The source-retrieval/enrichment trust boundary remains responsible for establishing
verification before such evidence reaches production use.


## SB-024 bounded deep research

`DeepResearchEngine` adds an iterative research controller above the existing SB-023 source-verifying
research engine. It assesses explicit evidence gaps after each round, generates bounded follow-up
queries for missing support, counter-evidence and source-family diversity, deduplicates evidence across
rounds and stops when evidence sufficiency is reached or marginal information gain falls below the
configured floor. Source collection remains subject to the existing HTTPS/SSRF/content-size guards.
Only the aggregated verified evidence bundle is passed to `NexusOrchestrator`; deep research does not
create a second final-decision engine.

## SB-025 — Curiosity & Research Planner

The deep-research layer now includes a bounded CuriosityPlanner. After an initial research pass it
asks what remains unknown, ranks those gaps by uncertainty, impact, expected information gain,
research cost and value-of-information, and selects only auditable follow-up questions. A missing
counter-evidence path is explicitly treated as a falsification question and receives deep-research
priority. The planner itself has no provider, network, apply, merge or deploy authority; it can only
emit ResearchQuery objects for the existing guarded ResearchEngine.

Mission Control exposes this through `POST /api/missions/autonomous-research` and displays the
planner's questions, expected gain, value-of-information, route and stop reason. Curiosity decisions
are also written into the durable audit trace as `curiosity_plan` events. NexusOrchestrator remains
the sole final-decision runtime.

## SB-026 — OSINT + Privacy Research

SB-026 adds GitHub REST repository discovery, DuckDuckGo search, composite research-provider routing, and application-level egress modes (`direct`, `http_proxy`, `socks5`, `tor`).

`.onion` retrieval is deliberately allowlist-gated and only accepts explicitly supplied onion URLs in the mission. There is no unrestricted dark-web crawler.

Mission Control defaults to local loopback operation and supports a stealth mode with a generated bearer token, no network discovery and suppressed HTTP request logging. Stealth is a local isolation/privacy feature; it does not claim universal anonymity or untraceability.


## SB-027 — World Model + Live OSINT Diagnostics

SB-027 adds a persistent World Model backed by SQLite. Evidence from completed missions is linked to a
proposition derived from the mission text. Novel evidence updates deterministic support/challenge
strength, confidence, source diversity, freshness and revision count. Belief states are descriptive
(`UNKNOWN`, `SUPPORTED`, `CONTESTED`, `REFUTED`, `UNCERTAIN`) and do not replace the Nexus final judge.

Mission Control adds `GET /api/world-model` and `POST /api/osint/diagnostics`. The live diagnostic uses
the same guarded GitHub and DuckDuckGo adapters as research, verifies one retrieved source, detects local
Tor SOCKS endpoints, checks the Tor Project status API when Tor is available, and runs a controlled
DuckDuckGo onion retrieval through an explicit temporary diagnostic allowlist. Credentials and response
bodies are not returned by the diagnostic API.
