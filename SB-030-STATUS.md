# SuperBrain SB-030 — Autonomous Intelligence Loop

## Purpose

SB-030 turns the existing Research + Nexus + World Model + Change Engine + Assurance components into one bounded autonomous intelligence loop.

**Observe → Select → Research → Nexus → World Model → Change Detection → Assurance → Continue / Escalate**

## Safety boundaries

- Nexus remains the canonical final decision engine.
- Autonomous cycles are bounded by mission, round and source budgets.
- Assurance can block continuation.
- High-impact external actions are not executed by this layer.
- No automatic code, policy, provider, routing or deployment mutation.
- A blocked cycle produces an explicit escalation action instead of silently continuing.
- World Model is descriptive memory, not an alternate decision engine.

## API

- `POST /api/autonomy/cycle` — execute one bounded autonomous cycle.
- `GET /api/autonomy/cycles` — inspect persisted cycle history.

Example body:

```json
{"missions":["Assess whether the proposition remains supported"],"cycle_id":"manual-cycle-1"}
```

## Test

SB-030 adds deterministic tests for execution, assurance blocking and safe no-work behavior.
