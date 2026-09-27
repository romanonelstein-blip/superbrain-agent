from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

from .deep_research import DeepResearchEngine, DeepResearchPolicy
from .mission_control import MissionControlService
from .models import Stance
from .provider_bridge import ProviderEvidence
from .research import ResearchEngine, RetrievedResearchSource, SearchHit


class _AcceptanceSearch:
    name = "sb024-acceptance-search"

    def search(self, query: str, limit: int):
        q = query.casefold()
        if "risks criticism counterevidence limitations" in q:
            return ()
        if "contrary evidence failure risks" in q:
            return (SearchHit("Counter", "https://counter.example/report", "counter", self.name, 1, query, Stance.NEUTRAL),)
        if "independent analysis study report dataset source" in q:
            return (SearchHit("Independent", "https://independent.example/study", "independent", self.name, 1, query, Stance.NEUTRAL),)
        return (
            SearchHit("Primary A", "https://primary-a.example/report", "a", self.name, 1, query, Stance.NEUTRAL),
            SearchHit("Primary B", "https://primary-b.example/report", "b", self.name, 2, query, Stance.NEUTRAL),
        )[:limit]


class _AcceptanceFetcher:
    def fetch(self, hit: SearchHit) -> RetrievedResearchSource:
        host = hit.url.split("/")[2]
        return RetrievedResearchSource(
            source_id="acceptance-" + host,
            source_family=host,
            title=hit.title,
            url=hit.url,
            excerpt=f"Deterministic independently retrieved acceptance evidence from {host}.",
            content_hash=hashlib.sha256(hit.url.encode("utf-8")).hexdigest(),
            retrieved_at="2026-09-20T00:00:00+00:00",
            content_type="text/html",
            query=hit.query,
            stance=hit.stance,
            search_provider=hit.provider,
            rank=hit.rank,
        )


def _synthesize(_task, _context):
    return (
        ProviderEvidence(
            evidence_id="sb024-acceptance-synthesis",
            claim="The bounded deep-research loop completed and preserved explicit counter-evidence and remaining uncertainty.",
            provider="fixture",
            model="sb024-deterministic",
            request_id="sb024-acceptance",
            agent="strategy",
            verified=False,
            attempts=1,
            latency_ms=0,
        ),
    )


def main() -> None:
    engine = DeepResearchEngine(
        ResearchEngine(_AcceptanceSearch(), source_fetcher=_AcceptanceFetcher()),
        policy=DeepResearchPolicy(max_rounds=3, max_total_sources=10),
    )
    with tempfile.TemporaryDirectory() as temporary:
        service = MissionControlService(
            Path(temporary) / "state.db",
            deep_research_engine=engine,
            research_synthesizer=_synthesize,
        )
        result = service.execute_deep_research_mission(
            "Should the evidence-backed launch proceed?",
            run_id="sb024-acceptance",
            max_rounds=3,
            max_total_sources=10,
        )
        detail = service.get_mission(result.run_id)
        print(json.dumps({
            "result": result.to_dict(),
            "audit": detail["audit"] if detail else [],
        }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
