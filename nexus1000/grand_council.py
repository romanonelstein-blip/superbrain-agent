from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from .evidence_graph import EvidenceGraph
from .models import (
    CouncilVerdict,
    Evidence,
    GrandCouncilMetrics,
    GrandCouncilResult,
    Stance,
)
from .neis import NEIS


@dataclass(frozen=True)
class EscalationBudget:
    max_rounds: int = 2
    max_extra_councils: int = 4
    min_novel_evidence_ratio: float = 0.20


@dataclass(frozen=True)
class GrandCouncilConfig:
    min_support_strength: float = 1.25
    min_independence: float = 0.60
    min_family_diversity: float = 0.40
    min_freshness: float = 0.50
    min_reliability: float = 0.55
    max_conflict_ratio: float = 0.45


class GrandCouncil:
    def __init__(
        self,
        neis: NEIS | None = None,
        config: GrandCouncilConfig | None = None,
        budget: EscalationBudget | None = None,
    ) -> None:
        self.neis = neis or NEIS()
        self.config = config or GrandCouncilConfig()
        self.budget = budget or EscalationBudget()

    @staticmethod
    def _flatten(councils: Iterable[CouncilVerdict]) -> tuple[Evidence, ...]:
        by_id: dict[str, Evidence] = {}
        for council in councils:
            for evidence in council.evidence:
                by_id[evidence.id] = evidence
        return tuple(by_id.values())

    @staticmethod
    def _has_unresolved_council_conflict(councils: Iterable[CouncilVerdict]) -> bool:
        return any(c.unresolved_conflict for c in councils)

    def _metrics(self, evidence: tuple[Evidence, ...], prior_ids: set[str]) -> GrandCouncilMetrics:
        graph = EvidenceGraph.from_evidence(evidence)
        return GrandCouncilMetrics(
            support_strength=graph.stance_strength(Stance.SUPPORT),
            challenge_strength=graph.stance_strength(Stance.CHALLENGE),
            independence=graph.independence_score(),
            family_diversity=graph.family_diversity_score(),
            freshness=graph.average_freshness(),
            reliability=graph.average_reliability(),
            conflict_ratio=graph.conflict_ratio(),
            novel_evidence_ratio=graph.novelty_ratio(prior_ids),
        )

    def _thresholds_pass(self, m: GrandCouncilMetrics) -> bool:
        return (
            m.support_strength >= self.config.min_support_strength
            and m.support_strength > m.challenge_strength
            and m.independence >= self.config.min_independence
            and m.family_diversity >= self.config.min_family_diversity
            and m.freshness >= self.config.min_freshness
            and m.reliability >= self.config.min_reliability
            and m.conflict_ratio <= self.config.max_conflict_ratio
        )

    def adjudicate(
        self,
        councils: list[CouncilVerdict],
        escalate_fn: Callable[[int, tuple[Evidence, ...]], list[CouncilVerdict]] | None = None,
    ) -> GrandCouncilResult:
        current = list(councils)
        initial_ids = {e.id for e in self._flatten(current)}
        escalated = False
        rounds = 0
        extra_councils_used = 0
        stop_reason = "initial evidence sufficient"

        while True:
            raw = self._flatten(current)
            neis_result = self.neis.evaluate(raw)
            usable = neis_result.usable
            metrics = self._metrics(usable, initial_ids if rounds > 0 else set())
            unresolved = self._has_unresolved_council_conflict(current)
            material_conflict = metrics.conflict_ratio > self.config.max_conflict_ratio
            provisional = neis_result.passed and self._thresholds_pass(metrics) and not unresolved and not material_conflict

            needs_escalation = (
                not provisional
                and escalate_fn is not None
                and rounds < self.budget.max_rounds
                and extra_councils_used < self.budget.max_extra_councils
            )

            if not needs_escalation:
                if not provisional:
                    if rounds >= self.budget.max_rounds:
                        stop_reason = "escalation round budget exhausted"
                    elif extra_councils_used >= self.budget.max_extra_councils:
                        stop_reason = "extra council budget exhausted"
                    elif escalate_fn is None:
                        stop_reason = "insufficient evidence and no escalation provider"
                    else:
                        stop_reason = "evidence thresholds not satisfied"
                return GrandCouncilResult(
                    provisional_yes=provisional,
                    evidence=usable,
                    quarantined_evidence_ids=neis_result.quarantined_ids,
                    unresolved_conflict=unresolved or material_conflict,
                    escalated=escalated,
                    escalation_rounds=rounds,
                    stop_reason=stop_reason,
                    metrics=metrics,
                    rationale=(
                        "Grand Council weighs evidence strength, independence, freshness, "
                        "reliability and conflict; it never counts council votes."
                    ),
                )

            remaining = self.budget.max_extra_councils - extra_councils_used
            additions = list(escalate_fn(rounds + 1, raw))[:remaining]
            if not additions:
                stop_reason = "escalation returned no new councils"
                return GrandCouncilResult(
                    provisional_yes=False,
                    evidence=usable,
                    quarantined_evidence_ids=neis_result.quarantined_ids,
                    unresolved_conflict=unresolved or material_conflict,
                    escalated=escalated,
                    escalation_rounds=rounds,
                    stop_reason=stop_reason,
                    metrics=metrics,
                    rationale="Escalation stopped because it produced no new council.",
                )

            before_ids = {e.id for e in raw}
            new_evidence = self._flatten(additions)
            new_ids = {e.id for e in new_evidence}
            novel = new_ids - before_ids
            novelty_ratio = len(novel) / len(new_ids) if new_ids else 0.0

            current.extend(additions)
            extra_councils_used += len(additions)
            rounds += 1
            escalated = True

            if novelty_ratio < self.budget.min_novel_evidence_ratio:
                # Recompute once with additions, but stop further escalation.
                raw = self._flatten(current)
                neis_result = self.neis.evaluate(raw)
                usable = neis_result.usable
                metrics = self._metrics(usable, initial_ids)
                unresolved = self._has_unresolved_council_conflict(current)
                material_conflict = metrics.conflict_ratio > self.config.max_conflict_ratio
                provisional = neis_result.passed and self._thresholds_pass(metrics) and not unresolved and not material_conflict
                return GrandCouncilResult(
                    provisional_yes=provisional,
                    evidence=usable,
                    quarantined_evidence_ids=neis_result.quarantined_ids,
                    unresolved_conflict=unresolved or material_conflict,
                    escalated=True,
                    escalation_rounds=rounds,
                    stop_reason="novelty below threshold; escalation stopped",
                    metrics=metrics,
                    rationale="Escalation halted because additional research stopped adding meaningful evidence.",
                )
