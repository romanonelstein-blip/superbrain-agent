# NEXUS-1000 v0.17 — World Model, OSINT Diagnostics & Persistent Intelligence

v0.15 adds durable SQL-backed state and semantic memory.

- persistent runs and evidence
- source reputation across runs
- agent performance history
- namespaced semantic memory
- cosine similarity + top-k retrieval
- restart-safe SQLite prototype
- PostgreSQL + pgvector production schema
- HNSW vector-index definition

Important: remembered data can influence routing and research prioritization,
but memory is never accepted automatically as fresh proof. Final decisions
still pass through the full evidence chain.

## v0.16 provider integration

`NexusOrchestrator` is the single canonical decision runtime. The TypeScript
package under `integrations/superbrain_orchestrator_v2` supplies provider/model
routing through an explicit JSON bridge; it does not make a canonical final
decision. Provider output enters Nexus as unverified evidence with provider,
model, agent, and request provenance. It must still pass Evidence Graph/NEIS,
blinded dissent, verifier, and final-judge gates.

`SourceEvidenceEnricher` is the trust boundary for promoting that output. A
claim becomes verified only when an independently resolved source has the
expected identity, contains the cited text, and a separately supplied checker
confirms that the citation supports its declared SUPPORT or CHALLENGE stance.
Provider-supplied `verified` values are ignored. Missing, mismatched, or
unsupported citations remain unverified and therefore fail closed.

`LocalDocumentResolver` is the first concrete retrieval adapter. It resolves
only pre-registered source IDs below one fixed root, accepts bounded UTF-8
`.txt`, `.md`, and `.json` documents, rejects path escapes and type mismatches,
and records the relative location, content type, SHA-256 hash, and retrieval
timestamp. Those citation fields survive the full Nexus pipeline and SQLite
reopen.

`HttpsSourceResolver` adds the remote equivalent for explicitly registered
HTTPS sources. Every hostname must be exactly allowlisted, every DNS answer
must be public, TLS connects to a prevalidated pinned IP while verifying the
original hostname, and every redirect is revalidated. Ports, redirects, time,
bytes, compression, charset, and media types are bounded. HTML remains blocked in this registered-source adapter; SB-023 adds a separate guarded HTML research extractor for search-discovered public pages.

When a `SQLiteStateStore` is attached, Nexus stores the final decision, the
evidence used by the Grand Council, and the per-run timeline audit trail.
Provider/model/request/agent/failover/latency provenance is stored with each
evidence item. Semantic memory is written only for a final YES whose verifier
gate passed and only when an embedding function is explicitly configured.

## SB-017 reflection and learning

`ControlledLearningLoop` is an optional post-decision layer on the canonical
`NexusOrchestrator`. It receives the mission, final result, gate outcomes, and
non-quarantined evidence only after the verifier passes. A reflector can return
structured `LessonProposal` values, but each proposal is rejected unless all
referenced evidence is verified, has citation and content-hash provenance, and
bounds the lesson confidence.

`SQLiteLearningStore` is deliberately separate from operational run state. It
deduplicates normalized lessons and improvement candidates, counts unique run
occurrences, and retains a per-run provenance snapshot. Improvement candidates
have the only supported status `PROPOSED`; this milestone contains no mechanism
that applies code, policy, prompt, routing, or other behavioral changes.

Run the deterministic cross-language acceptance mission with reflection enabled:

```text
python -m nexus1000.sb017_mission
```

## SB-018 Golden Evals and safe improvement gating

SB-018 adds a fixed five-task safety suite under `evals/`, a canonical Nexus
evaluation runner, and a baseline-versus-candidate promotion policy. Reports
contain accuracy, evidence-quality compliance, calibration score, deterministic
cost units, and live mean/maximum latency.

A candidate is rejected when any required metric or previously correct Golden
Task regresses, when a task exceeds its cost/latency budget, or when suite/report
identity differs. Equal metrics pass the quality gate but produce `NO_PROMOTION`.
Only a non-regressing candidate with a measurable primary quality improvement can
become `ELIGIBLE_FOR_EXPLICIT_APPROVAL`.

Eligibility never applies anything: every report records
`automatic_change_applied=false`, and no automatic code or behavior mutation path
exists. Run the comparison with:

```text
python -m nexus1000.sb018_eval --output-dir work/sb018-evals
```

The relevant-path workflow `.github/workflows/sb018-quality.yml` runs the complete
Python and TypeScript gates plus this comparison on runtime, test, eval, provider,
or workflow changes.

## SB-019 controlled experiment engine

SB-019 consumes an SB-017 `PROPOSED` improvement candidate without changing its
status. It creates a content-addressed immutable snapshot of the candidate,
artifacts, Golden Suite, accepted baseline, SB-018 thresholds, and executor ID;
runs the candidate against frozen Golden Tasks inside a disposable artifact
sandbox; revalidates the evaluation contract; and stores every metric, report,
artifact, event, and timestamp in an append-only SQLite experiment record.

Experiment decisions are limited to `REJECT`, `NO_IMPROVEMENT`, and
`ELIGIBLE_FOR_APPROVAL`. Eligibility still requires explicit approval and never
applies a change. Run the acceptance experiment with:

```text
python -m nexus1000.sb019_experiment
```

## SB-020 approval-gated apply transaction

SB-020 adds the only controlled apply path for an immutable SB-019 result. It accepts only
`ELIGIBLE_FOR_APPROVAL` experiments and a cryptographically verified, content-addressed
`HUMAN` approval bound to the exact experiment, snapshot, candidate, and Golden suite.
Approvals carry an exact explicit intent and are single-use.

Candidate input is a bounded declarative `replace` plan; shell commands, Python, hooks,
deletes, and executable fields are rejected. Before mutation, target hashes are checked and
a pre-apply snapshot is recorded. Writes use atomic replacement. The unchanged Golden suite
runs after apply; a regression restores the snapshot and verifies both restored hashes and
Golden behavior. Approval, transaction, events, reports, hashes, and rollback outcome are
append-only audit records. SB-020 has no deployment path and no AI/agent approval path.

Run the isolated acceptance transaction with:

```bash
python -m nexus1000.sb020_apply
```

The sandbox is an application-level isolation boundary for trusted executors. It
does not claim OS/container isolation for arbitrary hostile native or Python code.

## SB-021 provider resilience and live-validation boundary

SB-021 hardens the existing TypeScript provider boundary without changing Nexus-1000 as the
canonical decision runtime. The provider router now adds bounded retries for transient failures,
terminal handling for auth/bad-request failures, provider/model allowlists, a local circuit breaker,
rate limiting, total-attempt and latency budgets, deterministic cost-unit budgets, router-level
timeouts, secret-safe error sanitization, and explicit resilience metadata on successful executions.

Live vendor validation is deliberately opt-in. `npm run sb021:live-smoke` performs no network call
unless `SUPERBRAIN_LIVE_PROVIDER_SMOKE=1` is set and at least one real provider credential is
present. Fixture/offline success must never be reported as live-provider validation.

## SB-022 local Mission Control and runtime API

SB-022 adds a local, dependency-free control plane around the canonical `NexusOrchestrator`.
It does **not** create a second decision engine. Mission results, evidence and audit events remain
owned by `SQLiteStateStore`, while Master decisions are stored as a separate append-only review
layer and never rewrite the canonical Nexus result.

Start it locally:

```text
python -m nexus1000.sb022_server
```

Then open `http://127.0.0.1:8787/`. The UI can run a deterministic demo mission, list persisted
missions and display their evidence/audit trail. API endpoints expose health, system status,
mission listing/detail, evidence-mission execution and Master-decision recording.

Security defaults are fail-closed: Mission Control binds to loopback by default, request bodies
are bounded, JSON is required for mutation endpoints, browser security headers are set, and a
non-loopback bind is rejected unless `SUPERBRAIN_MISSION_CONTROL_TOKEN` is configured. SB-022
contains no automatic apply, merge, deploy or provider-live-validation path.

The generic `/api/missions` endpoint accepts **preverified source-backed evidence** and requires
citation plus content-hash provenance for items marked verified. It is a control-plane boundary, not a replacement for `SourceEvidenceEnricher`. SB-023 now adds a separate research endpoint for search discovery plus guarded public-HTTPS source retrieval.

## SB-022.1 interactive Mission Control

Mission Control now accepts your own mission in the browser. Start it with `start-mission-control.bat` on Windows and open `http://127.0.0.1:8787`.

For live draft specialist responses, copy `.env.example` to `.env`, configure at least one supported provider credential, then restart Mission Control. Provider output remains unverified until source-backed verification is added by the research milestone; NexusOrchestrator remains the canonical final-decision engine.

## SB-023 web research and evidence-backed answers

SB-023 adds a research path to Mission Control without changing the canonical decision engine.
The browser now offers **Research & answer** beside the existing quick model answer.

The runtime is:

```text
User mission
→ bounded research plan
→ Tavily or Brave Search discovery
→ URL deduplication
→ guarded public-HTTPS retrieval
→ HTML/text extraction + SHA-256 provenance
→ verified research Evidence
→ canonical NexusOrchestrator / NEIS / Dissent / Verifier / Final Judge
→ optional provider synthesis using the retrieved source context
→ Mission Control source cards + evidence/audit persistence
```

Search discovery itself is not treated as proof. A search result only becomes verified Nexus evidence
when SuperBrain independently retrieves the HTTPS page through the guarded source fetcher, records its
content hash and retrieval metadata, and creates a citation from the retrieved content. The web source
fetcher rejects non-HTTPS URLs, credentials in URLs, IP literals, non-public DNS targets, non-443 ports,
cross-host redirects, compressed payloads, unsupported content types, invalid UTF-8 and oversized bodies.

Natural-language synthesis remains model-generated and advisory. The Nexus `YES`/`NO` value shown in
research mode describes whether the **evidence bundle** cleared the canonical evidence gates; it is not a
claim that every sentence in the model synthesis has independently been verified.

Configure research by copying `.env.example` to `.env` and adding one of:

```text
TAVILY_API_KEY=...
BRAVE_SEARCH_API_KEY=...
```

Optionally choose the backend explicitly:

```text
SUPERBRAIN_WEB_SEARCH_PROVIDER=tavily
```

A model key (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY` or `GEMINI_API_KEY`) is optional for source collection
but required for a natural-language research synthesis. Without a model key, Mission Control still returns
the retrieved sources and Nexus evidence-gate result.

Run the deterministic, network-free SB-023 acceptance mission with:

```text
python -m nexus1000.sb023_mission
```


## SB-023.3 dashboard restoration

Mission Control now restores the complete dashboard while retaining interactive Quick answer and Research & answer. The dashboard includes overview metrics, runtime readiness, recent missions, evidence/provenance, audit timeline, selected mission details, Master Authority controls and runtime diagnostics.


## SB-024 deep research loop

Mission Control now includes a bounded `Deep research` mode. The deep layer repeatedly uses the
existing guarded `ResearchEngine`; it never bypasses HTTPS retrieval, provenance, or Nexus gates.
After each round it measures explicit knowledge gaps for support depth, counter-evidence and source
diversity. It can issue targeted follow-up queries and stops on evidence sufficiency, low marginal
information gain, the source budget, or the configured round cap. The dashboard exposes round count,
stop reason, remaining gaps and all retrieved sources.

Deep research API: `POST /api/missions/deep-research`.
Default limits: 3 rounds, 12 total sources, 3 search results per query.

## SB-025 curiosity and research planner

SB-025 adds a deterministic curiosity layer above the bounded deep-research loop. It does not
create a second decision engine and it does not call tools directly. NexusOrchestrator remains the
only final-decision engine.

After the first guarded research round, the CuriosityPlanner converts remaining evidence gaps into
explicit self-questions. Each question records uncertainty, decision impact, expected information
gain, estimated research cost, value-of-information, risk, priority, routing and whether it is an
active falsification question. Only `RESEARCH` and `DEEP_RESEARCH` questions become bounded
ResearchQuery objects; all source retrieval still goes through the existing guarded ResearchEngine.

The dashboard now exposes **Autonomous research**. Its API endpoint is:

```text
POST /api/missions/autonomous-research
```

Default limits are 4 rounds, 16 total sources and 3 results per query. The deep-research endpoint
remains available with its previous tighter defaults.

Run the deterministic, network-free acceptance mission with:

```text
python -m nexus1000.sb025_mission
```

## SB-026.1 Live connectivity smoke test

Run `run-live-osint-test.bat` on Windows to test the real machine/network using the same SuperBrain adapters. The test checks GitHub, DuckDuckGo and guarded source retrieval through the configured egress. It also independently probes `127.0.0.1:9150` and `:9050` for Tor, even when the application is configured for direct mode. On Windows the launcher can start an installed Tor Browser automatically and wait for its SOCKS endpoint. When Tor is available, the test also validates `check.torproject.org` and a safe DuckDuckGo onion service automatically; no custom onion target is required for the smoke test. It never prints credential values.

The current development environment cannot perform outbound DNS/network requests, so a Windows result is required before claiming live provider or Tor validation.

## SB-026 OSINT + Privacy Research

SuperBrain can now combine:

- GitHub public repository intelligence (and optional authenticated GitHub API access via `GITHUB_TOKEN`);
- DuckDuckGo HTML search;
- existing Tavily/Brave search providers;
- application-level direct/HTTP-proxy/SOCKS5/Tor egress;
- explicit, allowlisted `.onion` retrieval when Tor mode is enabled.

### Privacy mode

`SUPERBRAIN_STEALTH_MODE=1` keeps Mission Control on loopback and requires an API bearer token. The launcher opens the exact authenticated local URL. No network discovery or telemetry mechanism is added.

Stealth does **not** mean the application is universally invisible or untraceable. Provider-side records, endpoint security, browser state and the surrounding operating system remain outside this application's control.

### Controlled onion research

For production onion research, an onion hostname must still be explicitly allowlisted. The live smoke test uses a separate, temporary allowlist entry for DuckDuckGo so that the production policy remains closed by default.

To inspect an onion service, set:

```text
SUPERBRAIN_EGRESS_MODE=tor
SUPERBRAIN_PROXY_HOST=127.0.0.1
SUPERBRAIN_PROXY_PORT=9150
SUPERBRAIN_ONION_ALLOWLIST=example.onion
```

Then explicitly include the allowlisted `.onion` URL in the research mission. SB-026 does not implement an unrestricted dark-web crawler or automated interaction with illicit marketplaces/services.


## SB-027 World Model + Live OSINT Diagnostics

SB-027 adds a persistent evidence-weighted World Model above the existing Nexus pipeline. The model
tracks a proposition across missions, accumulates only novel evidence, and deterministically revises
its state between `UNKNOWN`, `SUPPORTED`, `CONTESTED`, `REFUTED` and `UNCERTAIN`. It records confidence,
support/challenge strength, source-family diversity, freshness and revision count. The World Model is
**descriptive memory, not a second final-decision engine**; `NexusOrchestrator` remains authoritative.

Mission Control now exposes:

- `GET /api/world-model?limit=50` for the persistent belief ledger;
- `POST /api/osint/diagnostics` for a bounded live probe from the machine running Mission Control;
- a World Model panel and selected-mission belief state;
- a live OSINT control that tests GitHub, DuckDuckGo, guarded source retrieval and, when a local Tor
  SOCKS endpoint is detected, Tor plus the controlled DuckDuckGo onion diagnostic.

The diagnostics endpoint reports only safe metadata and never returns API credentials or response bodies.
The onion diagnostic is separate from production research: arbitrary onion discovery remains disabled and
production onion retrieval remains explicitly allowlist-gated.

## SB-027 verification

- Full Python suite: **236/236 passed**.
- SB-027 targeted tests: **4/4 passed**.
- Python compile gate: passed.
- Mission Control JavaScript syntax check: passed.
- Deterministic SB-027 acceptance mission: passed; the World Model revised a repeated proposition from `SUPPORTED` to `CONTESTED`.
- Live OSINT path executed in the packaging environment; external DNS/network is unavailable there, so
  GitHub and DuckDuckGo correctly report `ResearchUnavailableError` rather than being claimed as live
  validated.

## SB-029 — Intelligence Feasibility & Assurance

SB-029 adds an explicit assurance layer for evaluating whether SuperBrain's observable behavior meets serious-autonomy requirements. It checks abstention, evidence independence, contradiction handling, calibration, provenance, recovery after belief reversal, and human authorization for high-impact actions. Results are persisted in the SQLite assurance ledger and exposed through `/api/assurance`.

Important: passing these deterministic cases does not establish general autonomous intelligence. It establishes that the safety/reliability control logic works for the cases represented by the suite. Real-world reliability requires external evaluation and live evidence.


## P0 durable autonomy scheduler and database recovery

The continuous-intelligence loop now has restart-safe schedule metadata in the canonical SQLite state database.

Run one due check:

```bash
python -m nexus1000.scheduler --database work/mission-control.sqlite3 --once --seed "Research this proposition"
```

Run continuously (an external process manager must restart this process after an OS/container restart):

```bash
python -m nexus1000.scheduler --database work/mission-control.sqlite3 --interval 900
```

The scheduler persists `next_run_at`, last cycle, failure count and bounded exponential backoff. A process restart therefore resumes the existing schedule rather than resetting it.

`SQLiteStateStore.backup_to(path)` creates a SQLite online backup and verifies `PRAGMA integrity_check`. `restore_from(path)` rejects missing/corrupt backups, restores into the live store, reruns schema migration and re-verifies database integrity.

Acceptance tests:

```bash
python -m unittest tests.test_v041_p0_durability -v
python -m unittest discover -s tests -p 'test*.py'
```

Current deterministic Python result: 250 tests passed. Live provider validation remains a separate production gate and requires explicit provider/search credentials.
