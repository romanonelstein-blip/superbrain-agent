# SuperBrain SB-028 — Temporal Change Engine

## Status

**SB-028 — COMPLETE (local implementation + deterministic verification).**

### Built

- Persistent `change_events` ledger in SQLite.
- `ChangeEngine` detects material belief changes after World Model revisions.
- Change classes include `SUPPORTED`, `CONTESTED`, `REFUTED`, `SUPPORT_RESTORED`, `STATE_CHANGED`, and `CONFIDENCE_SHIFT`.
- Severity is deterministic (`LOW`, `MEDIUM`, `HIGH`).
- Every material change links back to belief ID, mission/run ID, current/previous state and confidence.
- Change events are append-only application records; there is no automatic action/deployment path.
- New Mission Control endpoint: `GET /api/changes`.
- Dashboard now contains **What changed?** temporal intelligence feed.
- Runtime reports `change_engine_available=true` and build version `SB-028` while retaining SB-027 UI compatibility identifiers.

## Verification

- Full Python suite: **238/238 PASS**
- SB-028 targeted tests: **2/2 PASS**
- Python compile gate: **PASS**
- Existing SB-027 compatibility tests: **PASS**

## Design boundary

The Change Engine detects and explains material changes. It does not make the final mission decision, alter policies, modify code, deploy software, or bypass Master Authority. `NexusOrchestrator` remains the canonical final-decision engine.

## Live connectivity boundary

External GitHub, DuckDuckGo and Tor connectivity remains a machine/network-dependent live test. The local deterministic suite does not claim that external connectivity is live.
