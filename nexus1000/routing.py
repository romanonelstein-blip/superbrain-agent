from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .councils import SpecialistCouncil


@dataclass(frozen=True)
class ModelProfile:
    model_id: str
    domains: tuple[str, ...]
    capabilities: tuple[str, ...]
    quality: float
    latency: float
    cost: float

    def __post_init__(self) -> None:
        for name in ("quality", "latency", "cost"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")


@dataclass(frozen=True)
class ToolProfile:
    tool_id: str
    capabilities: tuple[str, ...]
    risk: float = 0.0
    cost: float = 0.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.risk <= 1.0:
            raise ValueError("risk must be in [0, 1]")
        if not 0.0 <= self.cost <= 1.0:
            raise ValueError("cost must be in [0, 1]")


@dataclass(frozen=True)
class RouteRequest:
    domains: tuple[str, ...]
    required_capabilities: tuple[str, ...] = ()
    min_quality: float = 0.65
    max_latency: float = 0.85
    max_cost: float = 0.85
    allow_high_risk_tools: bool = False

    def __post_init__(self) -> None:
        for name in ("min_quality", "max_latency", "max_cost"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")


@dataclass(frozen=True)
class RoutingBudget:
    max_councils: int = 4
    max_models: int = 2
    max_tools: int = 4
    max_total_cost_score: float = 3.0
    min_domain_overlap: float = 0.5

    def __post_init__(self) -> None:
        if self.max_councils < 1 or self.max_models < 1 or self.max_tools < 0:
            raise ValueError("routing budgets must be positive")


@dataclass(frozen=True)
class RoutePlan:
    council_ids: tuple[str, ...]
    model_ids: tuple[str, ...]
    tool_ids: tuple[str, ...]
    rejected: tuple[str, ...]
    estimated_cost_score: float
    fallback_used: bool
    rationale: tuple[str, ...]


class AdaptiveRouter:
    """
    Evidence-first router.

    Routing is selective: it minimizes activated resources while preserving
    coverage of requested domains/capabilities. It never decides the final answer.
    """

    def __init__(
        self,
        models: Iterable[ModelProfile] = (),
        tools: Iterable[ToolProfile] = (),
        budget: RoutingBudget | None = None,
    ) -> None:
        self.models = tuple(models)
        self.tools = tuple(tools)
        self.budget = budget or RoutingBudget()

    @staticmethod
    def _normalize(values: Iterable[str]) -> set[str]:
        return {v.strip().lower() for v in values if v and v.strip()}

    def _council_score(self, council: SpecialistCouncil, domains: set[str]) -> float:
        specialty = council.specialty.strip().lower()
        if not domains:
            return 1.0
        if specialty in domains:
            return 1.0
        # Conservative partial overlap for hierarchical names, e.g. legal/privacy.
        overlap = max(
            (1.0 if specialty == d else 0.65 if specialty in d or d in specialty else 0.0)
            for d in domains
        )
        return overlap

    def _model_score(self, model: ModelProfile, request: RouteRequest) -> float:
        domains = self._normalize(request.domains)
        capabilities = self._normalize(request.required_capabilities)
        model_domains = self._normalize(model.domains)
        model_caps = self._normalize(model.capabilities)

        if model.quality < request.min_quality:
            return -1.0
        if model.latency > request.max_latency:
            return -1.0
        if model.cost > request.max_cost:
            return -1.0

        domain_coverage = 1.0 if not domains else len(domains & model_domains) / len(domains)
        cap_coverage = 1.0 if not capabilities else len(capabilities & model_caps) / len(capabilities)

        # Prefer quality and coverage; penalize latency and cost.
        return (
            0.40 * model.quality
            + 0.25 * domain_coverage
            + 0.20 * cap_coverage
            + 0.10 * (1.0 - model.latency)
            + 0.05 * (1.0 - model.cost)
        )

    def _tool_score(self, tool: ToolProfile, request: RouteRequest) -> float:
        required = self._normalize(request.required_capabilities)
        tool_caps = self._normalize(tool.capabilities)
        coverage = 0.0 if not required else len(required & tool_caps) / len(required)

        if coverage <= 0:
            return -1.0
        if tool.risk > 0.7 and not request.allow_high_risk_tools:
            return -1.0

        return 0.65 * coverage + 0.20 * (1.0 - tool.risk) + 0.15 * (1.0 - tool.cost)

    def plan(
        self,
        request: RouteRequest,
        councils: list[SpecialistCouncil],
    ) -> RoutePlan:
        domains = self._normalize(request.domains)
        rejected: list[str] = []
        rationale: list[str] = []

        # Councils: pick only those with enough domain overlap.
        ranked_councils = sorted(
            ((self._council_score(c, domains), c) for c in councils),
            key=lambda x: x[0],
            reverse=True,
        )
        selected_councils: list[SpecialistCouncil] = []
        covered_domains: set[str] = set()

        for score, council in ranked_councils:
            if score < self.budget.min_domain_overlap:
                rejected.append(f"council:{council.council_id}:low_domain_overlap")
                continue
            if len(selected_councils) >= self.budget.max_councils:
                rejected.append(f"council:{council.council_id}:budget")
                continue
            selected_councils.append(council)
            spec = council.specialty.strip().lower()
            if spec in domains:
                covered_domains.add(spec)

        fallback_used = False
        if not selected_councils and councils:
            # Safe fallback: activate one deterministic council rather than zero.
            selected_councils = [councils[0]]
            fallback_used = True
            rationale.append("fallback council selected because no council met overlap threshold")

        # Models
        ranked_models = sorted(
            ((self._model_score(m, request), m) for m in self.models),
            key=lambda x: x[0],
            reverse=True,
        )
        selected_models: list[ModelProfile] = []
        for score, model in ranked_models:
            if score < 0:
                rejected.append(f"model:{model.model_id}:constraints")
                continue
            if len(selected_models) >= self.budget.max_models:
                rejected.append(f"model:{model.model_id}:budget")
                continue
            selected_models.append(model)

        # Tools
        ranked_tools = sorted(
            ((self._tool_score(t, request), t) for t in self.tools),
            key=lambda x: x[0],
            reverse=True,
        )
        selected_tools: list[ToolProfile] = []
        for score, tool in ranked_tools:
            if score < 0:
                rejected.append(f"tool:{tool.tool_id}:constraints_or_irrelevant")
                continue
            if len(selected_tools) >= self.budget.max_tools:
                rejected.append(f"tool:{tool.tool_id}:budget")
                continue
            selected_tools.append(tool)

        estimated_cost = sum(m.cost for m in selected_models) + sum(t.cost for t in selected_tools)
        if estimated_cost > self.budget.max_total_cost_score:
            # Trim most expensive resources until budget is met.
            combined = [
                ("model", m.model_id, m.cost) for m in selected_models
            ] + [
                ("tool", t.tool_id, t.cost) for t in selected_tools
            ]
            combined.sort(key=lambda x: x[2], reverse=True)
            to_drop: set[tuple[str, str]] = set()
            running = estimated_cost
            for kind, rid, cost in combined:
                if running <= self.budget.max_total_cost_score:
                    break
                to_drop.add((kind, rid))
                running -= cost
                rejected.append(f"{kind}:{rid}:total_cost_budget")

            selected_models = [m for m in selected_models if ("model", m.model_id) not in to_drop]
            selected_tools = [t for t in selected_tools if ("tool", t.tool_id) not in to_drop]
            estimated_cost = running

        if domains - covered_domains:
            rationale.append(
                "some requested domains remain uncovered; Genesis may create bounded specialists"
            )

        rationale.append(
            f"selected {len(selected_councils)} councils, "
            f"{len(selected_models)} models and {len(selected_tools)} tools"
        )

        return RoutePlan(
            council_ids=tuple(c.council_id for c in selected_councils),
            model_ids=tuple(m.model_id for m in selected_models),
            tool_ids=tuple(t.tool_id for t in selected_tools),
            rejected=tuple(rejected),
            estimated_cost_score=round(estimated_cost, 4),
            fallback_used=fallback_used,
            rationale=tuple(rationale),
        )
