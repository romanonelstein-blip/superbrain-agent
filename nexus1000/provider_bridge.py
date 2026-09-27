from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from .councils import SpecialistCouncil
from .models import CouncilVerdict, Evidence, Stance


@dataclass(frozen=True)
class ProviderEvidence:
    evidence_id: str
    claim: str
    provider: str
    model: str
    request_id: str | None = None
    agent: str = "provider"
    verified: bool = False
    reliability: float = 0.5
    freshness: float = 1.0
    relevance: float = 1.0
    attempts: int | None = None
    latency_ms: int | None = None


@dataclass(frozen=True)
class RetrievedSource:
    source_id: str
    source_family: str
    content: str
    content_hash: str | None = None
    retrieved_at: str | None = None
    location: str | None = None
    content_type: str | None = None


@dataclass(frozen=True)
class SourceBackedClaim:
    provider_evidence_id: str
    source_id: str
    quote: str
    stance: Stance = Stance.SUPPORT
    reliability: float = 0.5
    freshness: float = 1.0
    relevance: float = 1.0


class SourceEvidenceEnricher:
    """Promote claims only after independent retrieval and support checking."""

    def __init__(
        self,
        source_resolver: Callable[[str], RetrievedSource | None],
        citation_supports_stance: Callable[[str, Stance, str, str], bool],
    ) -> None:
        self.source_resolver = source_resolver
        self.citation_supports_stance = citation_supports_stance

    @staticmethod
    def _normalized(value: str) -> str:
        return " ".join(value.split()).casefold()

    def enrich(
        self,
        provider_items: Sequence[ProviderEvidence],
        citations: Sequence[SourceBackedClaim],
    ) -> tuple[Evidence, ...]:
        providers = {item.evidence_id: item for item in provider_items}
        by_provider: dict[str, list[SourceBackedClaim]] = {}
        for citation in citations:
            if citation.provider_evidence_id not in providers:
                raise ValueError(f"citation references unknown provider evidence: {citation.provider_evidence_id}")
            by_provider.setdefault(citation.provider_evidence_id, []).append(citation)

        enriched: list[Evidence] = []
        for item in provider_items:
            linked = by_provider.get(item.evidence_id, [])
            if not linked:
                enriched.extend(_unverified_provider_evidence((item,)))
                continue

            for citation in linked:
                source = self.source_resolver(citation.source_id)
                quote = self._normalized(citation.quote)
                content = self._normalized(source.content) if source else ""
                source_matches = source is not None and source.source_id == citation.source_id
                quote_matches = bool(quote) and quote in content
                semantically_supported = (
                    source_matches
                    and quote_matches
                    and self.citation_supports_stance(
                        item.claim, citation.stance, citation.quote, source.content
                    )
                )
                enriched.append(Evidence(
                    id=f"{item.evidence_id}:{citation.source_id}",
                    claim=item.claim,
                    stance=citation.stance,
                    source_id=citation.source_id,
                    source_family=source.source_family if source_matches else "unresolved-source",
                    reliability=citation.reliability,
                    freshness=citation.freshness,
                    relevance=citation.relevance,
                    verified=bool(semantically_supported),
                    citation=citation.quote,
                    content_hash=source.content_hash if source_matches else None,
                    retrieved_at=source.retrieved_at if source_matches else None,
                    location=source.location if source_matches else None,
                    content_type=source.content_type if source_matches else None,
                    provider=item.provider,
                    provider_model=item.model,
                    provider_request_id=item.request_id,
                    provider_agent=item.agent,
                    provider_attempts=item.attempts,
                    provider_latency_ms=item.latency_ms,
                ))
        return tuple(enriched)


def _unverified_provider_evidence(items: Sequence[ProviderEvidence]) -> tuple[Evidence, ...]:
    return tuple(Evidence(
        id=item.evidence_id,
        claim=item.claim,
        stance=Stance.SUPPORT,
        source_id=item.request_id or f"{item.provider}:{item.model}",
        source_family=item.provider,
        reliability=item.reliability,
        freshness=item.freshness,
        relevance=item.relevance,
        verified=False,
        provider=item.provider,
        provider_model=item.model,
        provider_request_id=item.request_id,
        provider_agent=item.agent,
        provider_attempts=item.attempts,
        provider_latency_ms=item.latency_ms,
    ) for item in items)


def councils_from_evidence(items: Sequence[Evidence]) -> list[SpecialistCouncil]:
    councils: list[SpecialistCouncil] = []
    for index, evidence in enumerate(items):
        council_id = f"evidence:{index}:{evidence.id}"
        verdict = CouncilVerdict(
            council_id=council_id,
            specialty="evidence",
            evidence=(evidence,),
            confidence=evidence.reliability,
            rationale="Evidence evaluated by the canonical Nexus pipeline.",
        )
        councils.append(SpecialistCouncil(council_id, "evidence", lambda _question, v=verdict: v))
    return councils


def councils_from_provider_evidence(items: Sequence[ProviderEvidence]) -> list[SpecialistCouncil]:
    # Provider declarations never establish verification. Only SourceEvidenceEnricher
    # may promote independently retrieved and checked material to verified Evidence.
    return councils_from_evidence(_unverified_provider_evidence(items))


class TypeScriptProviderBridge:
    """Run the TypeScript provider boundary and retain its provenance metadata."""

    def __init__(self, integration_dir: str | Path, command: Sequence[str] | None = None):
        self.integration_dir = Path(integration_dir)
        self.command = tuple(command or ("npm", "run", "nexus-bridge", "--silent"))

    def run(
        self,
        task: str,
        context: dict[str, Any] | None = None,
        preferred_agents: Sequence[str] | None = None,
    ) -> tuple[ProviderEvidence, ...]:
        request: dict[str, Any] = {"task": task, "context": context or {}}
        if preferred_agents:
            request["preferredAgents"] = list(preferred_agents)
        completed = subprocess.run(
            self.command,
            cwd=self.integration_dir,
            input=json.dumps(request),
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or "unknown provider failure"
            raise RuntimeError(f"TypeScript provider bridge failed: {detail[:1000]}")
        try:
            payload = json.loads(completed.stdout)
            return tuple(ProviderEvidence(**item) for item in payload["evidence"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("TypeScript provider bridge returned invalid JSON") from exc
