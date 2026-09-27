# SB-029 — Intelligence Feasibility & Assurance Layer

## Purpose
SB-029 makes the question **“Is SuperBrain actually behaving like a serious autonomous intelligence system?”** an explicit, continuously testable system concern.

This is an assurance layer, not a second decision engine. Nexus remains the canonical decision authority.

## What was added
- `nexus1000/assurance.py`
- deterministic assurance cases for:
  - abstention when evidence is missing
  - source-family independence
  - contradiction representation
  - calibration / unjustified certainty
  - provenance completeness
  - recovery after belief reversal
  - high-impact action gating
- persistent `assurance_runs` SQLite ledger
- test suite `tests/test_v039_sb029_assurance.py`

## Safety boundary
SB-029 cannot automatically change models, providers, prompts, policies, routing, code, deployment, or permissions. A failed assurance run is evidence for escalation/research, not an automatic self-modification trigger.

## Reality boundary
The suite is deterministic and local. It proves that the control logic behaves as designed; it does **not** prove open-world intelligence or real-world reliability. External live evaluations remain necessary.

## Acceptance
Run:

```text
python -m unittest discover -s tests -p "test_*.py" -v
python -m compileall nexus1000
```

The release is only considered green when both pass.
