# SB-023 — Web Research & Evidence-backed Mission Control

Status: **implemented and locally verified**.

## What was added

- `nexus1000/research.py`
  - bounded research-plan generation;
  - Tavily and Brave Search adapters using the Python standard library;
  - URL deduplication;
  - guarded public HTTPS retrieval with pinned DNS/IP validation;
  - HTML-to-text extraction;
  - content hashes, timestamps, source-family provenance and bounded excerpts;
  - verified `Evidence` creation only after independent source retrieval.
- `MissionControlService.execute_research_mission(...)`
  - research → verified evidence → canonical Nexus pipeline;
  - optional source-grounded model synthesis;
  - research events added to the durable audit trace.
- `POST /api/missions/research`
- Mission Control **Research & answer** UI with source cards.
- root `.env.example` entries for Tavily / Brave search.
- deterministic SB-023 acceptance mission.

## Canonical runtime

`NexusOrchestrator` remains the only final-decision engine. Search providers discover candidate URLs;
they do not determine the canonical result. Model-generated synthesis is not promoted to verified evidence.

## Verification performed in this workspace

```text
python -m unittest discover -s tests -p 'test*.py'
Ran 203 tests
OK
```

Additional gates:

```text
python -m compileall -q nexus1000 tests
node --check nexus1000/mission_control_web/app.js
python -m nexus1000.sb023_mission
```

All completed successfully.

The acceptance mission produced:

- 2 independently retrieved fixture sources;
- 2 verified evidence records;
- Nexus final evidence-gate value `YES`;
- research-plan / web-search / source-retrieval events preceding the normal Nexus audit trace;
- one advisory synthesis;
- zero automatic code, configuration, merge or deployment changes.

## Important proof boundary

No live Tavily or Brave request was executed in this build environment because no search credentials were
provided. The network adapters are therefore implemented and deterministically tested, but live vendor
validation remains pending until a real key is supplied on the user's machine.

The TypeScript provider source was not changed by SB-023. `npm test` was not re-run here because this clean
package intentionally contains no local `node_modules`/Vitest installation. The existing prebuilt bridge is
exercised by the Python integration suite; TypeScript dependency installation should still be revalidated on
the user's Windows workspace with `npm ci && npm test && npm run typecheck && npm run build:bridge`.
