# SB-034 live-provider proof gate

SB-034 is complete only when reproducible evidence is tied to one exact commit SHA.

## Required proof

- locked clean install succeeds
- build, lint and full tests succeed
- NEXUS core reports ready with `nexus1000/orchestrator.py` and `nexus1000/neis.py`
- a live provider returns verified, provenance-backed evidence
- one research run traverses `grand_council`, `neis`, `blinded_dissent`, and `verifier`
- final output records every required gate as `PASS`
- the approved live run finishes with NEXUS final value `YES`
- a negative run proves approval is denied when the evidence-provider step is unavailable
- CI writes `artifacts/sb034-live-proof.json` with the exact tested commit SHA

Mocks, static grep checks, configuration readiness, or CI from another SHA do not satisfy the live-provider requirement.

## CI configuration

The `SB-034 Auto Live Proof` workflow supports either HTTP research providers or a command evidence provider. Do not configure both modes at the same time.

Required for every live proof:

- `SUPERBRAIN_SB034_QUESTION` repository variable: the research question used for the proof
- a usable NEXUS-1000 core, preferably through `SUPERBRAIN_NEXUS_REPOSITORY`; the workflow checks it out into the runner and uses that exact copy

For a separate/private NEXUS repository, configure:

- `SUPERBRAIN_NEXUS_REPOSITORY` repository variable, for example `owner/nexus-core`
- optionally `SUPERBRAIN_NEXUS_REF` to pin a branch, tag, or commit
- `SUPERBRAIN_NEXUS_REPO_TOKEN` secret only when the default workflow token cannot read that repository

For HTTP research mode, configure:

- `SUPERBRAIN_RESEARCH_PRIMARY_ENDPOINT`
- `SUPERBRAIN_RESEARCH_DISSENT_ENDPOINT`
- optional provider names, source-host allowlist and diversity thresholds
- bearer tokens only as GitHub Actions secrets when the endpoints require them

The live proof captures provider names, source IDs, citations and content hashes, but never writes bearer tokens into the proof artifact.

## Result semantics

`PASS` means the same run produced provenance-backed live evidence, passed all four canonical NEXUS gates, returned final `YES`, and the negative provider-unavailable case failed closed.

Any missing runtime, provider, provenance field, required gate, or negative-case denial leaves SB-034 as `BLOCKED`.
