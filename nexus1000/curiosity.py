from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Iterable

from .models import Evidence, Stance
from .research import MAX_RESULTS_PER_QUERY, MAX_RESEARCH_SOURCES, ResearchPlan, ResearchQuery, _bounded_query


MAX_CURIOSITY_QUESTIONS = 6


class CuriosityRoute(str, Enum):
    IGNORE = "IGNORE"
    REMEMBER = "REMEMBER"
    RESEARCH = "RESEARCH"
    DEEP_RESEARCH = "DEEP_RESEARCH"
    ASK_MASTER = "ASK_MASTER"


@dataclass(frozen=True)
class CuriosityPolicy:
    max_questions: int = 3
    min_expected_information_gain: float = 0.20
    ask_master_risk_threshold: float = 0.90
    research_priority_threshold: float = 0.35

    def validate(self) -> None:
        if not 1 <= self.max_questions <= MAX_CURIOSITY_QUESTIONS:
            raise ValueError(f"max_questions must be between 1 and {MAX_CURIOSITY_QUESTIONS}")
        for name, value in (
            ("min_expected_information_gain", self.min_expected_information_gain),
            ("ask_master_risk_threshold", self.ask_master_risk_threshold),
            ("research_priority_threshold", self.research_priority_threshold),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")


@dataclass(frozen=True)
class CuriosityQuestion:
    question: str
    reason: str
    gap_code: str
    stance: Stance
    uncertainty: float
    impact: float
    expected_information_gain: float
    estimated_cost: float
    value_of_information: float
    risk: float
    priority: float
    route: CuriosityRoute
    falsification: bool = False

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["stance"] = self.stance.value
        payload["route"] = self.route.value
        return payload


@dataclass(frozen=True)
class CuriosityDecision:
    round_number: int
    questions: tuple[CuriosityQuestion, ...]
    continue_research: bool
    stop_reason: str | None
    total_expected_information_gain: float
    estimated_cost: float
    top_question: str | None
    falsification_question_present: bool

    def to_dict(self) -> dict:
        return {
            "round_number": self.round_number,
            "questions": [question.to_dict() for question in self.questions],
            "continue_research": self.continue_research,
            "stop_reason": self.stop_reason,
            "total_expected_information_gain": self.total_expected_information_gain,
            "estimated_cost": self.estimated_cost,
            "top_question": self.top_question,
            "falsification_question_present": self.falsification_question_present,
        }


class CuriosityPlanner:
    """Deterministic, bounded research-question planner.

    The planner does not call models or tools itself. It ranks explicit knowledge gaps by
    uncertainty, decision impact, expected information gain and bounded research cost, then
    emits only auditable ResearchQuery objects for the existing guarded ResearchEngine.
    """

    def __init__(self, policy: CuriosityPolicy | None = None) -> None:
        self.policy = policy or CuriosityPolicy()
        self.policy.validate()

    @staticmethod
    def _gap_attr(gap: object, name: str, default):
        return getattr(gap, name, default)

    @staticmethod
    def _question_for_gap(mission: str, code: str, stance: Stance) -> tuple[str, str, bool]:
        if code == "counterevidence":
            return (
                _bounded_query(
                    f"{mission} contrary evidence failure risks criticism limitations opposing view"
                ),
                "Actively try to falsify the current leading interpretation with credible counter-evidence.",
                True,
            )
        if code == "support-depth":
            return (
                _bounded_query(
                    f"{mission} primary source data report evidence official statistics"
                ),
                "Reduce uncertainty by adding independently retrieved primary supporting evidence.",
                False,
            )
        if code == "source-diversity":
            return (
                _bounded_query(
                    f"{mission} independent analysis study report dataset source"
                ),
                "Reduce evidence-lineage concentration by finding a genuinely independent source family.",
                False,
            )
        return (
            _bounded_query(f"{mission} latest independent evidence verification"),
            "Check whether another independent source materially changes the evidence state.",
            stance is Stance.CHALLENGE,
        )

    def assess(
        self,
        mission: str,
        gaps: Iterable[object],
        evidence: Iterable[Evidence],
        *,
        round_number: int,
        remaining_source_budget: int,
        previous_new_sources: int | None = None,
    ) -> CuriosityDecision:
        mission = " ".join(mission.split()).strip()
        if not mission:
            raise ValueError("mission cannot be empty")
        if round_number < 1:
            raise ValueError("round_number must be positive")
        if remaining_source_budget < 0:
            raise ValueError("remaining_source_budget cannot be negative")

        gaps = tuple(gaps)
        evidence = tuple(evidence)
        if not gaps:
            return CuriosityDecision(
                round_number=round_number,
                questions=(),
                continue_research=False,
                stop_reason="evidence_sufficiency_reached",
                total_expected_information_gain=0.0,
                estimated_cost=0.0,
                top_question=None,
                falsification_question_present=False,
            )
        if remaining_source_budget == 0:
            return CuriosityDecision(
                round_number=round_number,
                questions=(),
                continue_research=False,
                stop_reason="source_budget_exhausted",
                total_expected_information_gain=0.0,
                estimated_cost=0.0,
                top_question=None,
                falsification_question_present=False,
            )

        # Evidence diversity and prior round yield inform expected gain without letting the
        # planner silently redefine the verification policy.
        families = {item.source_family for item in evidence if item.source_family}
        diversity_factor = 1.0 if len(families) < 3 else 0.85
        if previous_new_sources is None:
            yield_factor = 1.0
        elif previous_new_sources <= 0:
            yield_factor = 0.45
        elif previous_new_sources == 1:
            yield_factor = 0.75
        else:
            yield_factor = 1.0
        budget_factor = min(1.0, max(0.25, remaining_source_budget / 6.0))

        candidates: list[CuriosityQuestion] = []
        for gap in gaps:
            code = str(self._gap_attr(gap, "code", "unknown"))
            stance = self._gap_attr(gap, "stance", Stance.NEUTRAL)
            if not isinstance(stance, Stance):
                stance = Stance(str(stance))
            raw_priority = float(self._gap_attr(gap, "priority", 50))
            uncertainty = max(0.05, min(1.0, raw_priority / 100.0))
            impact = {
                "counterevidence": 1.00,
                "support-depth": 0.90,
                "source-diversity": 0.80,
            }.get(code, 0.70)
            falsification = code == "counterevidence" or stance is Stance.CHALLENGE
            if falsification:
                impact = max(impact, 1.0)
            expected_gain = max(
                0.0,
                min(1.0, uncertainty * impact * diversity_factor * yield_factor * budget_factor),
            )
            estimated_cost = min(1.0, 0.12 + (0.04 * max(0, round_number - 1)) + (0.03 if falsification else 0.0))
            value_of_information = max(0.0, min(1.0, expected_gain / max(estimated_cost * 4.0, 0.05)))
            risk = 0.20 if falsification else 0.10
            priority = max(0.0, min(1.0, (value_of_information * 0.55) + (expected_gain * 0.25) + (impact * 0.20)))
            question, reason, falsification = self._question_for_gap(mission, code, stance)
            if risk >= self.policy.ask_master_risk_threshold:
                route = CuriosityRoute.ASK_MASTER
            elif expected_gain < self.policy.min_expected_information_gain:
                route = CuriosityRoute.REMEMBER
            elif falsification or priority >= 0.72:
                route = CuriosityRoute.DEEP_RESEARCH
            elif priority >= self.policy.research_priority_threshold:
                route = CuriosityRoute.RESEARCH
            else:
                route = CuriosityRoute.IGNORE
            candidates.append(CuriosityQuestion(
                question=question,
                reason=reason,
                gap_code=code,
                stance=stance,
                uncertainty=round(uncertainty, 6),
                impact=round(impact, 6),
                expected_information_gain=round(expected_gain, 6),
                estimated_cost=round(estimated_cost, 6),
                value_of_information=round(value_of_information, 6),
                risk=round(risk, 6),
                priority=round(priority, 6),
                route=route,
                falsification=falsification,
            ))

        candidates.sort(
            key=lambda item: (item.route is CuriosityRoute.ASK_MASTER, item.priority, item.expected_information_gain),
            reverse=True,
        )
        selected = tuple(candidates[: self.policy.max_questions])
        actionable = tuple(
            item for item in selected
            if item.route in {CuriosityRoute.RESEARCH, CuriosityRoute.DEEP_RESEARCH}
        )
        total_gain = round(sum(item.expected_information_gain for item in actionable), 6)
        total_cost = round(sum(item.estimated_cost for item in actionable), 6)
        top = actionable[0].question if actionable else (selected[0].question if selected else None)
        stop_reason = None
        continue_research = bool(actionable)
        if not continue_research:
            if any(item.route is CuriosityRoute.ASK_MASTER for item in selected):
                stop_reason = "master_input_required"
            else:
                stop_reason = "curiosity_information_gain_low"

        return CuriosityDecision(
            round_number=round_number,
            questions=selected,
            continue_research=continue_research,
            stop_reason=stop_reason,
            total_expected_information_gain=total_gain,
            estimated_cost=total_cost,
            top_question=top,
            falsification_question_present=any(item.falsification for item in selected),
        )

    def build_plan(
        self,
        mission: str,
        decision: CuriosityDecision,
        *,
        max_results_per_query: int,
        max_sources: int,
    ) -> ResearchPlan:
        if not 1 <= max_results_per_query <= MAX_RESULTS_PER_QUERY:
            raise ValueError(f"max_results_per_query must be between 1 and {MAX_RESULTS_PER_QUERY}")
        if not 1 <= max_sources <= MAX_RESEARCH_SOURCES:
            raise ValueError(f"max_sources must be between 1 and {MAX_RESEARCH_SOURCES}")
        queries: list[ResearchQuery] = []
        seen: set[tuple[str, Stance]] = set()
        for question in decision.questions:
            if question.route not in {CuriosityRoute.RESEARCH, CuriosityRoute.DEEP_RESEARCH}:
                continue
            key = (question.question.casefold(), question.stance)
            if key in seen:
                continue
            seen.add(key)
            queries.append(ResearchQuery(
                query=question.question,
                stance=question.stance,
                purpose=f"curiosity:{question.gap_code}; priority={question.priority:.3f}",
            ))
        if not queries:
            raise ValueError("curiosity decision has no actionable research questions")
        return ResearchPlan(
            mission=mission,
            queries=tuple(queries[: self.policy.max_questions]),
            max_results_per_query=max_results_per_query,
            max_sources=max_sources,
        )
