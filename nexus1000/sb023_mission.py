from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

from .mission_control import MissionControlService
from .models import Stance
from .provider_bridge import ProviderEvidence
from .research import ResearchEngine, RetrievedResearchSource, SearchHit


class _AcceptanceSearch:
    name = "sb023-fixture-search"

    def search(self, query: str, limit: int):
        if "counterevidence" in query:
            return ()
        rows = (
            SearchHit(
                "Independent market source",
                "https://market.example/evidence",
                "Independent demand evidence.",
                self.name,
                1,
                query,
                Stance.NEUTRAL,
            ),
            SearchHit(
                "Independent customer source",
                "https://customer.example/evidence",
                "Independent customer evidence.",
                self.name,
                2,
                query,
                Stance.NEUTRAL,
            ),
        )
        return rows[:limit]


class _AcceptanceFetcher:
    def fetch(self, hit: SearchHit) -> RetrievedResearchSource:
        host = hit.url.split("/")[2]
        excerpt = (
            f"Independently retrieved source material from {host} supports the evidence-backed "
            "acceptance mission and is preserved with content provenance."
        )
        return RetrievedResearchSource(
            source_id=f"fixture-{host}",
            source_family=host,
            title=hit.title,
            url=hit.url,
            excerpt=excerpt,
            content_hash=hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
            retrieved_at="2026-09-20T00:00:00+00:00",
            content_type="text/html",
            query=hit.query,
            stance=hit.stance,
            search_provider=hit.provider,
            rank=hit.rank,
        )


def _synthesize(_task: str, _context: dict):
    return (
        ProviderEvidence(
            evidence_id="sb023-synthesis",
            claim=(
                "The two independently retrieved sources clear the evidence-quality gate for the "
                "acceptance mission. This synthesis remains advisory rather than independently verified text."
            ),
            provider="fixture",
            model="sb023-synthesis-fixture",
            request_id="sb023-synthesis",
            agent="strategy",
            verified=False,
            attempts=1,
            latency_ms=0,
        ),
    )


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        service = MissionControlService(
            Path(temporary) / "sb023.db",
            research_engine=ResearchEngine(
                _AcceptanceSearch(),
                source_fetcher=_AcceptanceFetcher(),
            ),
            research_synthesizer=_synthesize,
        )
        result = service.execute_research_mission(
            "Should the independently researched acceptance mission proceed?",
            run_id="sb023-acceptance",
        )
        detail = service.get_mission(result.run_id)
        print(json.dumps({
            "result": result.to_dict(),
            "audit": detail["audit"] if detail else [],
            "persisted_evidence": detail["evidence"] if detail else [],
            "automatic_change_application": False,
            "live_web_validation_claimed": False,
        }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
