from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from .models import Evidence


@dataclass(frozen=True)
class NEISResult:
    passed: bool
    usable: tuple[Evidence, ...]
    quarantined_ids: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class NEISConfig:
    max_family_share: float = 0.60
    min_source_families: int = 2


class NEIS:
    """NEXUS Evidence Independence System."""

    def __init__(self, config: NEISConfig | None = None) -> None:
        self.config = config or NEISConfig()

    def evaluate(self, evidence: tuple[Evidence, ...]) -> NEISResult:
        if not evidence:
            return NEISResult(False, (), (), "no evidence")

        family_counts = Counter(e.source_family for e in evidence)
        total = len(evidence)
        dominant_family, dominant_count = family_counts.most_common(1)[0]
        dominant_share = dominant_count / total

        quarantined: list[str] = []
        usable = list(evidence)

        if dominant_share > self.config.max_family_share and len(family_counts) > 1:
            # Quarantine enough dominant-family items to bring concentration under the cap.
            dominant = [e for e in evidence if e.source_family == dominant_family]
            others = [e for e in evidence if e.source_family != dominant_family]
            # Keep highest-quality dominant evidence first.
            dominant.sort(key=lambda e: (e.reliability * e.freshness * e.relevance), reverse=True)
            keep_n = max(1, int((self.config.max_family_share * len(others)) / (1 - self.config.max_family_share)))
            keep_dom = dominant[:keep_n]
            quarantine_dom = dominant[keep_n:]
            usable = others + keep_dom
            quarantined = [e.id for e in quarantine_dom]

        usable_families = {e.source_family for e in usable}
        passed = len(usable_families) >= self.config.min_source_families
        reason = "independence satisfied" if passed else "insufficient independent source families"
        return NEISResult(passed, tuple(usable), tuple(quarantined), reason)
