import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from nexus1000.deep_research import DeepResearchEngine, DeepResearchPolicy
from nexus1000.mission_control import MissionControlService
from nexus1000.models import Stance
from nexus1000.provider_bridge import ProviderEvidence
from nexus1000.research import ResearchEngine, RetrievedResearchSource, SearchHit
from nexus1000.sb022_server import build_server


class ProgressiveSearch:
    name = "sb024-search"

    def search(self, query, limit):
        q = query.casefold()
        if "risks criticism counterevidence limitations" in q:
            return ()
        if "contrary evidence failure risks" in q:
            return (SearchHit("Counter", "https://c.example/c", "c", self.name, 1, query, Stance.NEUTRAL),)
        if "independent analysis study report dataset source" in q:
            return (SearchHit("Independent", "https://d.example/d", "d", self.name, 1, query, Stance.NEUTRAL),)
        return (
            SearchHit("A", "https://a.example/a", "a", self.name, 1, query, Stance.NEUTRAL),
            SearchHit("B", "https://b.example/b", "b", self.name, 2, query, Stance.NEUTRAL),
        )[:limit]


class Fetcher:
    def fetch(self, hit):
        host = hit.url.split("/")[2]
        return RetrievedResearchSource(
            source_id="source-" + host,
            source_family=host,
            title=hit.title,
            url=hit.url,
            excerpt=f"Independent published evidence from {host} relevant to the tested proposition.",
            content_hash=hashlib.sha256(hit.url.encode()).hexdigest(),
            retrieved_at="2026-09-20T00:00:00+00:00",
            content_type="text/html",
            query=hit.query,
            stance=hit.stance,
            search_provider=hit.provider,
            rank=hit.rank,
        )


def synthesize(_task, _context):
    return (
        ProviderEvidence(
            evidence_id="deep-synthesis:strategy",
            claim="Deep research found both supporting evidence and an explicit counter-evidence path.",
            provider="openai",
            model="fixture",
            request_id="deep-synthesis-1",
            agent="strategy",
            verified=False,
            attempts=1,
            latency_ms=1,
        ),
    )


def make_engine():
    return DeepResearchEngine(
        ResearchEngine(ProgressiveSearch(), source_fetcher=Fetcher()),
        policy=DeepResearchPolicy(max_rounds=3, max_total_sources=10),
    )


class TestSB024EndToEnd(unittest.TestCase):
    def test_deep_research_runs_multiple_rounds_then_nexus(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = MissionControlService(
                Path(temporary) / "state.db",
                deep_research_engine=make_engine(),
                research_synthesizer=synthesize,
            )
            result = service.execute_deep_research_mission(
                "Should this evidence-backed launch proceed?",
                run_id="sb024-e2e",
                max_rounds=3,
                max_total_sources=10,
            )
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.deep_research["round_count"], 2)
            self.assertEqual(result.deep_research["stop_reason"], "evidence_sufficiency_reached")
            self.assertGreaterEqual(result.evidence_count, 3)
            self.assertEqual(result.draft_responses[0]["agent"], "strategy")
            detail = service.get_mission("sb024-e2e")
            stages = [item["stage"] for item in detail["audit"]]
            self.assertIn("deep_research_start", stages)
            self.assertEqual(stages.count("deep_research_round"), 2)
            self.assertIn("deep_research_stop", stages)
            self.assertIn("verifier", stages)


class TestSB024HTTP(unittest.TestCase):
    def test_deep_research_route_returns_rounds_and_stop_reason(self):
        with tempfile.TemporaryDirectory() as temporary:
            server = build_server("127.0.0.1", 0, Path(temporary) / "state.db")
            server.service.deep_research_engine = make_engine()
            server.service.research_synthesizer = synthesize
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                payload = json.dumps({
                    "mission": "Should this evidence-backed launch proceed?",
                    "max_rounds": 3,
                    "max_total_sources": 10,
                }).encode("utf-8")
                req = Request(
                    base + "/api/missions/deep-research",
                    data=payload,
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urlopen(req, timeout=5) as response:
                    body = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 201)
                self.assertEqual(body["deep_research"]["round_count"], 2)
                self.assertEqual(body["deep_research"]["stop_reason"], "evidence_sufficiency_reached")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
