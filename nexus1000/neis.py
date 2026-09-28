from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .models import Evidence


@dataclass(frozen=True)
class NEISResult:
    passed: bool
    reasons: tuple[str, ...]


class NEIS:
    """NEXUS Evidence Integrity Standard.

    NEIS is deliberately fail-closed: every item used for approval must carry
    verified provenance and valid bounded scoring fields.
    """

    def evaluate(self, evidence: Iterable[Evidence]) -> NEISResult:
        items = tuple(evidence)
        reasons: list[str] = []
        if not items:
            return NEISResult(False, ("NEIS requires evidence.",))

        missing = [item.id for item in items if not item.provenance_complete]
        if missing:
            reasons.append(f"Missing verified provenance for: {', '.join(missing)}.")

        invalid_scores = [
            item.id
            for item in items
            if not all(0.0 <= score <= 1.0 for score in (item.reliability, item.freshness, item.relevance))
        ]
        if invalid_scores:
            reasons.append(f"Out-of-range evidence scores for: {', '.join(invalid_scores)}.")

        duplicate_ids = len({item.id for item in items}) != len(items)
        if duplicate_ids:
            reasons.append("Evidence IDs must be unique.")

        duplicate_sources = len({item.source_id for item in items}) != len(items)
        if duplicate_sources:
            reasons.append("Primary evidence sources must be unique.")

        if not reasons:
            reasons.append("NEIS verified provenance, score bounds, and source uniqueness.")
        return NEISResult(len(reasons) == 1 and reasons[0].startswith("NEIS verified"), tuple(reasons))
