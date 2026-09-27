from __future__ import annotations

import hashlib
from dataclasses import dataclass, asdict
from typing import Any

from .persistence import SQLiteStateStore
from .world_model import BeliefRevision, BeliefState


@dataclass(frozen=True)
class ChangeEvent:
    change_id: str
    belief_id: str
    run_id: str
    event_type: str
    severity: str
    title: str
    detail: str
    previous_state: str | None
    current_state: str
    previous_confidence: float | None
    current_confidence: float
    created_at: str
    acknowledged: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ChangeEngine:
    """Detect material world-model changes without making decisions."""

    STATE_PRIORITY = {
        BeliefState.UNKNOWN.value: 0,
        BeliefState.UNCERTAIN.value: 1,
        BeliefState.SUPPORTED.value: 2,
        BeliefState.CONTESTED.value: 3,
        BeliefState.REFUTED.value: 4,
    }

    def __init__(self, store: SQLiteStateStore) -> None:
        self.store = store

    @staticmethod
    def _severity(event_type: str, delta: float) -> str:
        if event_type in {"REFUTED", "SUPPORT_LOST", "CONTESTED"}:
            return "HIGH"
        if event_type in {"SUPPORTED", "STATE_CHANGED"} or abs(delta) >= 0.15:
            return "MEDIUM"
        return "LOW"

    def detect(self, revision: BeliefRevision, *, run_id: str, now: str) -> ChangeEvent | None:
        current = revision.belief
        previous = revision.previous_state.value if revision.previous_state else None
        previous_conf = revision.previous_confidence
        if not revision.changed or not revision.added_evidence_ids:
            return None

        if current.state is BeliefState.REFUTED:
            event_type = "REFUTED"
            title = "Belief moved to REFUTED"
        elif current.state is BeliefState.CONTESTED:
            event_type = "CONTESTED"
            title = "Belief is now CONTESTED"
        elif current.state is BeliefState.SUPPORTED and previous in {BeliefState.CONTESTED.value, BeliefState.REFUTED.value}:
            event_type = "SUPPORT_RESTORED"
            title = "Support recovered for belief"
        elif current.state is BeliefState.SUPPORTED:
            event_type = "SUPPORTED"
            title = "Belief gained material support"
        elif previous is not None and previous != current.state.value:
            event_type = "STATE_CHANGED"
            title = f"Belief changed {previous} → {current.state.value}"
        else:
            delta = current.confidence - (previous_conf or 0.0)
            event_type = "CONFIDENCE_SHIFT"
            title = "Belief confidence changed"

        delta = current.confidence - (previous_conf or 0.0)
        severity = self._severity(event_type, delta)
        digest = hashlib.sha256(f"{current.belief_id}|{run_id}|{event_type}|{current.confidence:.6f}".encode()).hexdigest()[:24]
        event = ChangeEvent(
            change_id=f"change-{digest}",
            belief_id=current.belief_id,
            run_id=run_id,
            event_type=event_type,
            severity=severity,
            title=title,
            detail=(f"{len(revision.added_evidence_ids)} new evidence item(s); "
                    f"confidence {previous_conf if previous_conf is not None else 0.0:.3f} → {current.confidence:.3f}; "
                    f"{revision.reason}."),
            previous_state=previous,
            current_state=current.state.value,
            previous_confidence=previous_conf,
            current_confidence=current.confidence,
            created_at=now,
        )
        self.store.add_change_event(event.to_dict())
        return event

    def list(self, limit: int = 50, *, unacknowledged_only: bool = False) -> tuple[dict[str, Any], ...]:
        return tuple(self.store.list_change_events(limit, unacknowledged_only=unacknowledged_only))
