from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable

from .models import CouncilVerdict, Evidence
from .councils import SpecialistCouncil


@dataclass(frozen=True)
class ExpertiseGap:
    domain: str
    reason: str
    priority: float
    required_capabilities: tuple[str, ...]

    def __post_init__(self) -> None:
        if not 0.0 <= self.priority <= 1.0:
            raise ValueError("priority must be in [0, 1]")


@dataclass(frozen=True)
class SpecialistBlueprint:
    specialist_id: str
    domain: str
    mission: str
    allowed_capabilities: tuple[str, ...]
    forbidden_capabilities: tuple[str, ...] = ()
    max_evidence_items: int = 8
    ttl_runs: int = 1

    def __post_init__(self) -> None:
        if self.max_evidence_items < 1:
            raise ValueError("max_evidence_items must be >= 1")
        if self.ttl_runs < 1:
            raise ValueError("ttl_runs must be >= 1")


@dataclass(frozen=True)
class GenesisBudget:
    max_specialists_per_run: int = 3
    min_gap_priority: float = 0.60
    max_capabilities_per_specialist: int = 4


@dataclass
class GenesisAudit:
    gaps_detected: list[ExpertiseGap] = field(default_factory=list)
    blueprints_created: list[SpecialistBlueprint] = field(default_factory=list)
    rejected_gaps: list[str] = field(default_factory=list)


class ExpertiseGapDetector:
    """
    Detects missing specialist domains from an explicit requirement map.
    This prototype deliberately avoids free-form self-expansion: new agents
    can only be created for declared capability gaps.
    """

    def detect(
        self,
        required_domains: dict[str, tuple[str, ...]],
        active_specialties: Iterable[str],
        evidence: tuple[Evidence, ...],
    ) -> list[ExpertiseGap]:
        active = {x.strip().lower() for x in active_specialties}
        gaps: list[ExpertiseGap] = []

        evidence_text = " ".join(
            f"{e.claim} {e.source_family} {e.source_id}".lower()
            for e in evidence
        )

        for domain, capabilities in required_domains.items():
            normalized = domain.strip().lower()
            if normalized in active:
                continue

            # Priority increases slightly if evidence already hints that
            # this domain is material to the run.
            hinted = normalized in evidence_text
            priority = 0.85 if hinted else 0.70
            gaps.append(
                ExpertiseGap(
                    domain=normalized,
                    reason=f"required domain '{normalized}' has no active specialist",
                    priority=priority,
                    required_capabilities=tuple(capabilities),
                )
            )

        return sorted(gaps, key=lambda g: g.priority, reverse=True)


class SpecialistGenesisEngine:
    """
    Creates temporary, least-privilege specialist blueprints.

    It does NOT invent tools or grant arbitrary permissions. Every capability
    must be present in the caller-provided capability registry.
    """

    def __init__(
        self,
        capability_registry: set[str],
        budget: GenesisBudget | None = None,
    ) -> None:
        self.capability_registry = set(capability_registry)
        self.budget = budget or GenesisBudget()
        self.audit = GenesisAudit()

    def create_blueprints(self, gaps: list[ExpertiseGap]) -> list[SpecialistBlueprint]:
        created: list[SpecialistBlueprint] = []

        for gap in gaps:
            self.audit.gaps_detected.append(gap)

            if gap.priority < self.budget.min_gap_priority:
                self.audit.rejected_gaps.append(
                    f"{gap.domain}: priority below threshold"
                )
                continue

            allowed = tuple(
                cap for cap in gap.required_capabilities
                if cap in self.capability_registry
            )[: self.budget.max_capabilities_per_specialist]

            if not allowed:
                self.audit.rejected_gaps.append(
                    f"{gap.domain}: no permitted capabilities"
                )
                continue

            bp = SpecialistBlueprint(
                specialist_id=f"genesis:{gap.domain}",
                domain=gap.domain,
                mission=(
                    f"Investigate only the '{gap.domain}' evidence gap. "
                    "Return evidence, provenance, uncertainty and counterevidence. "
                    "Do not decide the final answer."
                ),
                allowed_capabilities=allowed,
                forbidden_capabilities=("final_judge", "policy_override", "spawn_unbounded"),
                max_evidence_items=8,
                ttl_runs=1,
            )
            created.append(bp)
            self.audit.blueprints_created.append(bp)

            if len(created) >= self.budget.max_specialists_per_run:
                break

        return created

    def instantiate(
        self,
        blueprint: SpecialistBlueprint,
        runner_factory: Callable[[SpecialistBlueprint], Callable[[str], CouncilVerdict]],
    ) -> SpecialistCouncil:
        run_fn = runner_factory(blueprint)

        def bounded_run(question: str) -> CouncilVerdict:
            verdict = run_fn(question)
            evidence = tuple(verdict.evidence[: blueprint.max_evidence_items])
            return CouncilVerdict(
                council_id=blueprint.specialist_id,
                specialty=blueprint.domain,
                evidence=evidence,
                confidence=verdict.confidence,
                unresolved_conflict=verdict.unresolved_conflict,
                rationale=verdict.rationale,
            )

        return SpecialistCouncil(
            council_id=blueprint.specialist_id,
            specialty=blueprint.domain,
            run_fn=bounded_run,
        )
