# SB-034 live-provider proof gate

SB-034 is complete only when reproducible evidence is tied to one exact commit SHA and every build/test/proof step runs against that same SHA.

## Required proof

- locked clean install succeeds on the exact proof SHA
- build, lint and full tests succeed on the exact proof SHA
- NEXUS core reports ready with `nexus1000/orchestrator.py` and `nexus1000/neis.py`
- a live provider returns verified, provenance-backed evidence from external HTTPS sources
- one research run traverses `grand_council`, `neis`, `blinded_dissent`, and `verifier`
- final output records every required gate as `PASS`
- the approved live run finishes with NEXUS final value `YES`
- a negative run proves approval is denied when the evidence-provider step is unavailable
- CI writes `artifacts/sb034-live-proof.json` with the exact tested commit SHA

Mocks, static grep checks, configuration readiness, or CI from another SHA do not satisfy the live-provider requirement.

## Default CI runtime

The proof branch is self-contained by default:

- `nexus1000/` contains the fail-closed NEXUS-1000 reference runtime used by the bridge;
- `scripts/sb034-github-live-provider.mjs` performs real HTTPS retrieval from GitHub for the exact tested SHA and an independent npm-registry supply-chain cross-check for blinded dissent;
- the live provider hashes retrieved bytes and records citation, source family, provider identity, trust boundary, and content hash;
- pull-request checkout is pinned to the PR head SHA instead of GitHub's temporary merge ref;
- the default proof question and provider require no repository secrets.

Repository variables may override the default provider or point CI at a separate NEXUS core. External configuration must satisfy exactly the same proof contract and must not weaken fail-closed behavior.

## Result semantics

`PASS` means the same exact-SHA run produced provenance-backed live evidence, passed all four canonical NEXUS gates, returned final `YES`, and the negative provider-unavailable case failed closed.

Any missing runtime, provider, provenance field, required gate, exact-SHA binding, or negative-case denial leaves SB-034 as `BLOCKED`.
