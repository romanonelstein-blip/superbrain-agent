from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable


class Stance(str, Enum):
    SUPPORT = "support"
    CHALLENGE = "challenge"
    NEUTRAL = "neutral"


@dataclass(frozen=True)
class Evidence:
    id: str
    claim: str
    stance: Stance
    source_id: str
    source_family: str
    reliability: float = 0.5
    freshness: float = 1.0
    relevance: float = 1.0
    verified: bool = True
    citation: str | None = None
    content_hash: str | None = None
    retrieved_at: str | None = None
    location: str | None = None
    content_type: str | None = None
    provider: str | None = None
    provider_model: str | None = None
    provider_request_id: str | None = None
    provider_agent: str | None = None
    provider_attempts: int | None = None
    provider_latency_ms: int | None = None

    def __post_init__(self) -> None:
        for name in ("reliability", "freshness", "relevance"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")


@dataclass(frozen=True)
class CouncilVerdict:
    council_id: str
    specialty: str
    evidence: tuple[Evidence, ...]
    confidence: float
    unresolved_conflict: bool = False
    rationale: str = ""

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")


@dataclass(frozen=True)
class GrandCouncilMetrics:
    support_strength: float
    challenge_strength: float
    independence: float
    family_diversity: float
    freshness: float
    reliability: float
    conflict_ratio: float
    novel_evidence_ratio: float


@dataclass(frozen=True)
class GrandCouncilResult:
    provisional_yes: bool
    evidence: tuple[Evidence, ...]
    quarantined_evidence_ids: tuple[str, ...]
    unresolved_conflict: bool
    escalated: bool
    escalation_rounds: int
    stop_reason: str
    metrics: GrandCouncilMetrics
    rationale: str


@dataclass(frozen=True)
class FinalDecision:
    value: str
    reasons: tuple[str, ...]
    pipeline_passes: dict[str, bool]
    grand_council: GrandCouncilResult

    def __post_init__(self) -> None:
        if self.value not in {"YES", "NO"}:
            raise ValueError("FinalDecision.value must be YES or NO")
