# SB-025 — Curiosity & Research Planner

Status: **COMPLETE in the packaged local runtime**.

## Added

- `nexus1000/curiosity.py`
  - bounded self-question generation from explicit knowledge gaps;
  - uncertainty / impact / expected-information-gain scoring;
  - estimated research cost and value-of-information;
  - routes: `IGNORE`, `REMEMBER`, `RESEARCH`, `DEEP_RESEARCH`, `ASK_MASTER`;
  - explicit falsification questions for missing counter-evidence;
  - auditable conversion into existing `ResearchPlan` / `ResearchQuery` contracts.
- Curiosity-aware follow-up planning inside `DeepResearchEngine`.
- `curiosity_plan` events in the durable Mission Control audit trace.
- `POST /api/missions/autonomous-research` with bounded defaults.
- Mission Control **Autonomous research** control and visual curiosity-question trace.
- `python -m nexus1000.sb025_mission` deterministic acceptance mission.
- New unit/integration/HTTP tests.

## Quality gates executed in the packaging environment

- Full Python suite: **221/221 passed**.
- New SB-025 tests: **9/9 passed**.
- `python -m compileall -q nexus1000 tests`: passed.
- Mission Control JavaScript syntax check: passed.
- Prebuilt Nexus provider bridge JavaScript syntax check: passed.
- SB-021 offline provider-resilience self-test: passed.
- Deterministic SB-025 acceptance mission: passed.
  - completed runtime;
  - 2 research rounds;
  - curiosity questions generated;
  - falsification question present;
  - `curiosity_plan` audit event present;
  - canonical Nexus final decision remained independent of the planner.

## Safety boundary

SB-025 does not add automatic code changes, prompt mutation, merge, push, deployment or unrestricted
agent/tool spawning. The planner can only propose bounded research questions. Existing source
retrieval policy, provenance, evidence verification and Nexus final-decision gates remain in force.

## Environment note

The TypeScript source layer was not modified by SB-025. The full npm/Vitest suite was not reinstalled
in this Linux packaging environment because the portable ZIP intentionally does not ship `node_modules`.
The prebuilt bridge syntax and offline resilience self-test were executed successfully. On the target
Windows workspace, run `npm ci`, `npm test`, `npm run typecheck` and `npm run build:bridge` for the
platform-specific final TypeScript gate.
