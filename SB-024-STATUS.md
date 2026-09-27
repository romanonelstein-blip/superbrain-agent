# SB-024 — Deep Research Loop

Status: **COMPLETE (deterministic/local validation)**

SB-024 adds a bounded iterative research controller above the existing SB-023 guarded research engine. It does not replace `NexusOrchestrator` and does not introduce another final-decision path.

## Canonical flow

```text
Master mission
→ DeepResearchEngine
→ round 1: primary + counter-evidence search
→ guarded source retrieval / provenance
→ explicit knowledge-gap assessment
→ targeted follow-up query/queries when justified
→ marginal-information-gain / sufficiency stop rule
→ aggregated verified evidence
→ NexusOrchestrator
→ Grand Council / NEIS / Dissent / Verifier / Final Judge
→ advisory model synthesis (when a model provider is configured)
→ Mission Control
```

## Stop reasons

- `evidence_sufficiency_reached`
- `marginal_information_gain_low`
- `source_budget_exhausted`
- `max_rounds_reached`

Default limits in Mission Control are 3 rounds, 12 total sources and 3 search results per query.

## Dashboard

The restored SB-023.3 dashboard remains intact and now adds **Deep research** next to **Research & answer** and **Quick answer**. The response panel displays research rounds, stop reason, remaining evidence gaps and retrieved sources.

## Verification performed

```text
python -m unittest discover -s tests -p 'test*.py'
Ran 212 tests
OK
```

New SB-024 tests: **8/8 passed**.

Additional gates:

```text
python -m compileall -q nexus1000 tests
node --check nexus1000/mission_control_web/app.js
```

Both returned exit code 0.

Deterministic acceptance:

```text
python -m nexus1000.sb024_mission
```

Observed acceptance result:

```text
status = completed
round_count = 2
stop_reason = evidence_sufficiency_reached
evidence_count = 4
remaining_gaps = 0
Nexus final value = NO
```

The `NO` is intentional evidence behavior, not a failed run: the second round introduced explicit counter-evidence and Nexus remained the final decision engine.

## New / changed implementation

- `nexus1000/deep_research.py` — bounded research rounds, knowledge-gap assessment and stop rules
- `nexus1000/mission_control.py` — deep-research mission integration
- `nexus1000/sb022_server.py` — `/api/missions/deep-research`
- `nexus1000/mission_control_web/index.html` — Deep research control, SB-024 identity
- `nexus1000/mission_control_web/app.js` — deep-research UI and round/gap rendering
- `nexus1000/sb024_mission.py` — deterministic acceptance mission
- `nexus1000/__init__.py` — public deep-research exports
- `tests/test_v032_deep_research.py`
- `tests/test_v033_sb024_e2e.py`
- `tests/test_v028_mission_control.py` — current UI milestone assertions
- `README.md`
- `SUPERBRAIN-INTEGRATION.md`

## Evidence boundary

A search hit is still not automatically trusted. Each source continues through the SB-023 guarded retrieval and provenance path before it can become verified `Evidence`. Deep research only controls whether another bounded search round is justified.

No autonomous code apply, merge, push or deployment is introduced by SB-024.
