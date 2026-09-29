from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from .models import Evidence, Stance
from .neis import NEIS


@dataclass(frozen=True)
class CouncilResult:
    evidence: tuple[Evidence, ...]


@dataclass(frozen=True)
class FinalDecision:
    value: str
    pipeline_passes: dict[str, bool]
    reasons: tuple[str, ...]
    grand_council: CouncilResult


class NexusOrchestrator:
    """Deterministic NEXUS-1000 reference orchestrator.

    Approval is fail-closed and requires four independent gates:
    Grand Council, NEIS, blinded dissent, and verifier.
    """

    def __init__(self) -> None:
        self._neis = NEIS()

    def run_evidence_mission(
        self,
        question: str,
        evidence: Iterable[Evidence],
        *,
        dissent_fn: Callable[[str, tuple[Evidence, ...]], Iterable[Evidence]] | None = None,
        run_id: str | None = None,
    ) -> FinalDecision:
        del run_id
        primary = tuple(evidence)
        reasons: list[str] = []

        primary_families = {item.source_family for item in primary if item.source_family}
        grand_council = bool(
            question.strip()
            and len(primary) >= 2
            and len(primary_families) >= 2
            and all(item.stance in (Stance.SUPPORT, Stance.NEUTRAL) for item in primary)
        )
        reasons.append(
            "Grand Council accepted multi-source primary evidence."
            if grand_council
            else "Grand Council requires a non-empty question, at least two source families, and non-challenge primary evidence."
        )

        neis_result = self._neis.evaluate(primary)
        neis = neis_result.passed
        reasons.extend(neis_result.reasons)

        dissent_items: tuple[Evidence, ...] = ()
        if dissent_fn is not None:
            try:
                dissent_items = tuple(dissent_fn(question, primary))
            except Exception:
                dissent_items = ()

        primary_source_ids = {item.source_id for item in primary}
        primary_hashes = {item.content_hash for item in primary if item.content_hash}
        primary_boundaries = {item.trust_boundary for item in primary if item.trust_boundary}
        dissent = bool(
            dissent_items
            and all(item.stance == Stance.CHALLENGE for item in dissent_items)
            and all(item.provenance_complete for item in dissent_items)
            and all(item.source_id not in primary_source_ids for item in dissent_items)
            and all(not item.content_hash or item.content_hash not in primary_hashes for item in dissent_items)
            and all(item.trust_boundary not in primary_boundaries for item in dissent_items)
        )
        reasons.append(
            "Blinded dissent supplied provenance-backed challenge evidence from an independent trust boundary."
            if dissent
            else "Blinded dissent requires verified challenge evidence from a trust boundary independent of all primary evidence."
        )

        all_items = primary + dissent_items
        verifier = bool(
            grand_council
            and neis
            and dissent
            and all(item.provenance_complete for item in all_items)
            and len({item.id for item in all_items}) == len(all_items)
        )
        reasons.append(
            "Verifier confirmed all prior gates and end-to-end provenance."
            if verifier
            else "Verifier refused approval because a prior gate or provenance invariant failed."
        )

        pipeline_passes = {
            "grand_council": grand_council,
            "neis": neis,
            "blinded_dissent": dissent,
            "verifier": verifier,
        }
        approved = all(pipeline_passes.values())
        return FinalDecision(
            value="YES" if approved else "NO",
            pipeline_passes=pipeline_passes,
            reasons=tuple(reasons),
            grand_council=CouncilResult(primary),
        )
