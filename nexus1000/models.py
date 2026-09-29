from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


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
    trust_boundary: str
    reliability: float = 0.5
    freshness: float = 1.0
    relevance: float = 1.0
    verified: bool = False
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

    @property
    def provenance_complete(self) -> bool:
        return bool(
            self.verified
            and self.citation
            and self.content_hash
            and self.provider
            and self.source_id
            and self.source_family
            and self.trust_boundary
        )
