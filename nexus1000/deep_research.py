from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

from .models import Evidence, Stance
from .curiosity import CuriosityDecision, CuriosityPlanner
from .research import (
    MAX_RESEARCH_SOURCES,
    MAX_RESULTS_PER_QUERY,
    ResearchEngine,
    ResearchOutcome,
    ResearchPlan,
    ResearchQuery,
    RetrievedResearchSource,
    _bounded_query,
    build_research_plan,
)


MAX_DEEP_RESEARCH_ROUNDS = 5
MAX_DEEP_RESEARCH_SOURCES = 20


@dataclass(frozen=True)
class DeepResearchPolicy:
    max_rounds: int = 3
    max_total_sources: int = 12
    max_results_per_query: int = 3
    min_source_families: int = 3
    min_support_sources: int = 2
    min_challenge_sources: int = 1
    min_new_sources_per_round: int = 1

    def validate(self) -> None:
        if not 1 <= self.max_rounds <= MAX_DEEP_RESEARCH_ROUNDS:
            raise ValueError(f"max_rounds must be between 1 and {MAX_DEEP_RESEARCH_ROUNDS}")
        if not 1 <= self.max_total_sources <= MAX_DEEP_RESEARCH_SOURCES:
            raise ValueError(f"max_total_sources must be between 1 and {MAX_DEEP_RESEARCH_SOURCES}")
        if not 1 <= self.max_results_per_query <= MAX_RESULTS_PER_QUERY:
            raise ValueError(f"max_results_per_query must be between 1 and {MAX_RESULTS_PER_QUERY}")
        if not 1 <= self.min_source_families <= self.max_total_sources:
            raise ValueError("min_source_families must fit within max_total_sources")
        if self.min_support_sources < 0 or self.min_challenge_sources < 0:
            raise ValueError("source minimums cannot be negative")
        if not 1 <= self.min_new_sources_per_round <= self.max_total_sources:
            raise ValueError("min_new_sources_per_round is out of bounds")


@dataclass(frozen=True)
class KnowledgeGap:
    code: str
    description: str
    priority: int
    stance: Stance

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["stance"] = self.stance.value
        return payload


@dataclass(frozen=True)
class DeepResearchRound:
    round_number: int
    plan: ResearchPlan
    outcome: ResearchOutcome
    new_source_ids: tuple[str, ...]
    knowledge_gaps_before: tuple[KnowledgeGap, ...]
    knowledge_gaps_after: tuple[KnowledgeGap, ...]
    curiosity_decision: CuriosityDecision | None = None

    def to_dict(self) -> dict:
        return {
            "round_number": self.round_number,
            "plan": self.plan.to_dict(),
            "outcome": self.outcome.to_dict(),
            "new_source_ids": list(self.new_source_ids),
            "knowledge_gaps_before": [gap.to_dict() for gap in self.knowledge_gaps_before],
            "knowledge_gaps_after": [gap.to_dict() for gap in self.knowledge_gaps_after],
            "curiosity_decision": self.curiosity_decision.to_dict() if self.curiosity_decision else None,
        }


@dataclass(frozen=True)
class DeepResearchOutcome:
    mission: str
    rounds: tuple[DeepResearchRound, ...]
    sources: tuple[RetrievedResearchSource, ...]
    evidence: tuple[Evidence, ...]
    stop_reason: str
    knowledge_gaps: tuple[KnowledgeGap, ...]
    total_queries: int
    skipped_results: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "mission": self.mission,
            "rounds": [item.to_dict() for item in self.rounds],
            "round_count": len(self.rounds),
            "sources": [source.to_dict() for source in self.sources],
            "evidence_count": len(self.evidence),
            "stop_reason": self.stop_reason,
            "knowledge_gaps": [gap.to_dict() for gap in self.knowledge_gaps],
            "total_queries": self.total_queries,
            "skipped_results": list(self.skipped_results),
            "curiosity_questions": [
                question.to_dict()
                for round_item in self.rounds
                if round_item.curiosity_decision is not None
                for question in round_item.curiosity_decision.questions
            ],
        }


def assess_knowledge_gaps(
    evidence: Iterable[Evidence],
    *,
    policy: DeepResearchPolicy,
) -> tuple[KnowledgeGap, ...]:
    items = tuple(evidence)
    support = sum(1 for item in items if item.stance is Stance.SUPPORT)
    challenge = sum(1 for item in items if item.stance is Stance.CHALLENGE)
    families = {item.source_family for item in items if item.source_family}
    gaps: list[KnowledgeGap] = []
    if support < policy.min_support_sources:
        gaps.append(KnowledgeGap(
            "support-depth",
            f"Need {policy.min_support_sources - support} more independently retrieved supporting source(s).",
            100,
            Stance.SUPPORT,
        ))
    if challenge < policy.min_challenge_sources:
        gaps.append(KnowledgeGap(
            "counterevidence",
            f"Need {policy.min_challenge_sources - challenge} more retrieved counter-evidence source(s).",
            95,
            Stance.CHALLENGE,
        ))
    if len(families) < policy.min_source_families:
        gaps.append(KnowledgeGap(
            "source-diversity",
            f"Need evidence from {policy.min_source_families - len(families)} additional independent source family/families.",
            85,
            Stance.NEUTRAL,
        ))
    return tuple(sorted(gaps, key=lambda item: item.priority, reverse=True))


def build_followup_plan(
    mission: str,
    gaps: tuple[KnowledgeGap, ...],
    *,
    round_number: int,
    max_results_per_query: int,
    max_sources: int,
) -> ResearchPlan:
    queries: list[ResearchQuery] = []
    seen: set[tuple[str, Stance]] = set()

    def add(text: str, stance: Stance, purpose: str) -> None:
        query = _bounded_query(text)
        key = (query.casefold(), stance)
        if key in seen:
            return
        seen.add(key)
        queries.append(ResearchQuery(query, stance, purpose))

    for gap in gaps:
        if gap.code == "support-depth":
            add(
                f"{mission} primary source data report evidence official statistics",
                Stance.SUPPORT,
                "close support evidence gap",
            )
        elif gap.code == "counterevidence":
            add(
                f"{mission} contrary evidence failure risks criticism limitations opposing view",
                Stance.CHALLENGE,
                "actively falsify the leading conclusion",
            )
        elif gap.code == "source-diversity":
            add(
                f"{mission} independent analysis study report dataset source",
                Stance.NEUTRAL,
                "increase source independence",
            )

    if not queries:
        add(
            f"{mission} latest independent evidence verification",
            Stance.NEUTRAL,
            "marginal information gain check",
        )

    # A round must remain bounded and auditable. At most three targeted queries are emitted.
    queries = queries[:3]
    return ResearchPlan(
        mission=mission,
        queries=tuple(queries),
        max_results_per_query=max_results_per_query,
        max_sources=max_sources,
    )


class DeepResearchEngine:
    """Bounded iterative research above the existing source-verifying ResearchEngine.

    It never bypasses ResearchEngine retrieval policy. It only decides whether another bounded
    round is justified and deduplicates evidence across rounds before Nexus sees it.
    """

    def __init__(
        self,
        research_engine: ResearchEngine,
        *,
        policy: DeepResearchPolicy | None = None,
        curiosity_planner: CuriosityPlanner | None = None,
    ) -> None:
        self.research_engine = research_engine
        self.policy = policy or DeepResearchPolicy()
        self.policy.validate()
        self.curiosity_planner = curiosity_planner or CuriosityPlanner()

    def run(self, mission: str) -> DeepResearchOutcome:
        mission = " ".join(mission.split()).strip()
        if not mission:
            raise ValueError("mission cannot be empty")

        sources_by_id: dict[str, RetrievedResearchSource] = {}
        evidence_by_id: dict[str, Evidence] = {}
        skipped: list[str] = []
        rounds: list[DeepResearchRound] = []
        gaps = assess_knowledge_gaps((), policy=self.policy)
        stop_reason = "max_rounds_reached"
        total_queries = 0

        for round_number in range(1, self.policy.max_rounds + 1):
            remaining_sources = self.policy.max_total_sources - len(sources_by_id)
            if remaining_sources <= 0:
                stop_reason = "source_budget_exhausted"
                break

            curiosity_decision = None
            if round_number == 1:
                plan = build_research_plan(
                    mission,
                    max_results_per_query=self.policy.max_results_per_query,
                    max_sources=min(MAX_RESEARCH_SOURCES, remaining_sources),
                )
            else:
                previous_new_sources = len(rounds[-1].new_source_ids) if rounds else None
                curiosity_decision = self.curiosity_planner.assess(
                    mission,
                    gaps,
                    evidence_by_id.values(),
                    round_number=round_number,
                    remaining_source_budget=remaining_sources,
                    previous_new_sources=previous_new_sources,
                )
                if not curiosity_decision.continue_research:
                    stop_reason = curiosity_decision.stop_reason or "curiosity_information_gain_low"
                    break
                plan = self.curiosity_planner.build_plan(
                    mission,
                    curiosity_decision,
                    max_results_per_query=self.policy.max_results_per_query,
                    max_sources=min(MAX_RESEARCH_SOURCES, remaining_sources),
                )

            total_queries += len(plan.queries)
            before = gaps
            outcome = self.research_engine.run(plan)
            skipped.extend(outcome.skipped_results)
            new_ids: list[str] = []
            for source, evidence in zip(outcome.sources, outcome.evidence):
                if source.source_id in sources_by_id:
                    continue
                if len(sources_by_id) >= self.policy.max_total_sources:
                    break
                sources_by_id[source.source_id] = source
                evidence_by_id[evidence.id] = evidence
                new_ids.append(source.source_id)

            gaps = assess_knowledge_gaps(evidence_by_id.values(), policy=self.policy)
            rounds.append(DeepResearchRound(
                round_number=round_number,
                plan=plan,
                outcome=outcome,
                new_source_ids=tuple(new_ids),
                knowledge_gaps_before=before,
                knowledge_gaps_after=gaps,
                curiosity_decision=curiosity_decision,
            ))

            if not gaps:
                stop_reason = "evidence_sufficiency_reached"
                break
            if round_number > 1 and len(new_ids) < self.policy.min_new_sources_per_round:
                stop_reason = "marginal_information_gain_low"
                break
        else:
            stop_reason = "max_rounds_reached"

        return DeepResearchOutcome(
            mission=mission,
            rounds=tuple(rounds),
            sources=tuple(sources_by_id.values()),
            evidence=tuple(evidence_by_id.values()),
            stop_reason=stop_reason,
            knowledge_gaps=gaps,
            total_queries=total_queries,
            skipped_results=tuple(skipped),
        )
