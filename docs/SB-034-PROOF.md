# SB-034 live-provider proof gate

SB-034 is complete only when evidence is tied to one exact commit SHA.

## Required proof

- locked clean install succeeds
- build, lint and full tests succeed
- NEXUS core reports ready with `nexus1000/orchestrator.py` and `nexus1000/neis.py`
- a live provider returns provenance-backed evidence
- one run traverses `grand_council`, `neis`, `blinded_dissent`, and `verifier`
- final output records every required gate
- a negative run proves approval is denied if a required provider step or NEXUS gate fails
- CI evidence is tied to the tested commit SHA

Mocks, static grep checks, or CI from another SHA do not satisfy the live-provider requirement.

Until all requirements above are evidenced, status is `BLOCKED`, not `PASS`.
