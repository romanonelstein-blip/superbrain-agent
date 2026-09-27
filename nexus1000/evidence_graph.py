from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from .models import Evidence, Stance


@dataclass
class EvidenceGraph:
    evidence_by_id: dict[str, Evidence]

    @classmethod
    def from_evidence(cls, evidence: list[Evidence] | tuple[Evidence, ...]) -> "EvidenceGraph":
        return cls({e.id: e for e in evidence})

    def deduplicated(self) -> tuple[Evidence, ...]:
        # Evidence DNA: exact evidence IDs are immutable identities.
        return tuple(self.evidence_by_id.values())

    def source_family_counts(self) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for e in self.evidence_by_id.values():
            counts[e.source_family] += 1
        return dict(counts)

    def independence_score(self) -> float:
        evidence = list(self.evidence_by_id.values())
        if not evidence:
            return 0.0
        unique_sources = len({e.source_id for e in evidence})
        return unique_sources / len(evidence)

    def family_diversity_score(self) -> float:
        evidence = list(self.evidence_by_id.values())
        if not evidence:
            return 0.0
        unique_families = len({e.source_family for e in evidence})
        return unique_families / len(evidence)

    def average_freshness(self) -> float:
        values = [e.freshness for e in self.evidence_by_id.values()]
        return sum(values) / len(values) if values else 0.0

    def average_reliability(self) -> float:
        values = [e.reliability for e in self.evidence_by_id.values()]
        return sum(values) / len(values) if values else 0.0

    def stance_strength(self, stance: Stance) -> float:
        # Evidence strength, never a vote count.
        total = 0.0
        for e in self.evidence_by_id.values():
            if e.stance == stance:
                verification = 1.0 if e.verified else 0.35
                total += e.reliability * e.freshness * e.relevance * verification
        return total

    def conflict_ratio(self) -> float:
        support = self.stance_strength(Stance.SUPPORT)
        challenge = self.stance_strength(Stance.CHALLENGE)
        total = support + challenge
        if total == 0:
            return 1.0
        return min(support, challenge) / max(support, challenge) if max(support, challenge) else 1.0

    def novelty_ratio(self, prior_ids: set[str]) -> float:
        all_ids = set(self.evidence_by_id)
        if not all_ids:
            return 0.0
        novel = all_ids - prior_ids
        return len(novel) / len(all_ids)
