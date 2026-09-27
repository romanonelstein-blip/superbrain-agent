from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class TimelineEvent:
    stage: str
    message: str
    ts: str


@dataclass
class Timeline:
    events: list[TimelineEvent] = field(default_factory=list)

    def emit(self, stage: str, message: str) -> None:
        self.events.append(
            TimelineEvent(
                stage=stage,
                message=message,
                ts=datetime.now(timezone.utc).isoformat(),
            )
        )
