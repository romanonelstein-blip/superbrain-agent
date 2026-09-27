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


class CuriositySearch:
    name = "sb025-search"

    def search(self, query, limit):
        q = query.casefold()
        if "contrary evidence failure risks" in q:
            return (SearchHit("Counter", "https://counter.example/report", "counter", self.name, 1, query, Stance.NEUTRAL),)
        if "independent analysis study report dataset source" in q:
            return (SearchHit("Independent", "https://independent.example/study", "independent", self.name, 1, query, Stance.NEUTRAL),)
        if "primary source data report evidence official statistics" in q:
            return (SearchHit("Primary", "https://primary.example/data", "primary", self.name, 1, query, Stance.NEUTRAL),)
        return (
            SearchHit("Support A", "https://support-a.example/a", "a", self.name, 1, query, Stance.NEUTRAL),
            SearchHit("Support B", "https://support-b.example/b", "b", self.name, 2, query, Stance.NEUTRAL),
        )[:limit]


class Fetcher:
    def fetch(self, hit):
        host = hit.url.split("/")[2]
        return RetrievedResearchSource(
            source_id="source-" + host,
            source_family=host,
            title=hit.title,
            url=hit.url,
            excerpt=f"Verified published evidence from {host} relevant to the mission.",
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
            evidence_id="sb025-synthesis",
            claim="The research planner explicitly searched for missing evidence and falsification paths.",
            provider="openai",
            model="fixture",
            request_id="sb025-synthesis",
            agent="strategy",
            verified=False,
            attempts=1,
            latency_ms=1,
        ),
    )


def make_engine():
    return DeepResearchEngine(
        ResearchEngine(CuriositySearch(), source_fetcher=Fetcher()),
        policy=DeepResearchPolicy(max_rounds=4, max_total_sources=12),
    )


class TestSB025EndToEnd(unittest.TestCase):
    def test_curiosity_planner_generates_falsification_question_and_audit(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = MissionControlService(
                Path(temporary) / "state.db",
                deep_research_engine=make_engine(),
                research_synthesizer=synthesize,
            )
            result = service.execute_deep_research_mission(
                "Should this evidence-backed launch proceed?",
                run_id="sb025-e2e",
                max_rounds=4,
                max_total_sources=12,
            )
            self.assertEqual(result.status, "completed")
            self.assertGreaterEqual(result.deep_research["round_count"], 2)
            questions = result.deep_research["curiosity_questions"]
            self.assertTrue(questions)
            self.assertTrue(any(item["falsification"] for item in questions))
            self.assertTrue(any(item["route"] == "DEEP_RESEARCH" for item in questions))
            detail = service.get_mission("sb025-e2e")
            stages = [item["stage"] for item in detail["audit"]]
            self.assertIn("curiosity_plan", stages)
            self.assertIn("verifier", stages)


class TestSB025HTTP(unittest.TestCase):
    def test_dashboard_serves_sb025_autonomous_research_control(self):
        with tempfile.TemporaryDirectory() as temporary:
            server = build_server("127.0.0.1", 0, Path(temporary) / "state.db")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                with urlopen(base + "/", timeout=5) as response:
                    html = response.read().decode("utf-8")
                self.assertEqual(response.status, 200)
                self.assertIn("SB-027 · WORLD MODEL + OSINT", html)
                self.assertIn('id="autonomous-research"', html)
                self.assertIn('id="deep-research"', html)
                self.assertIn('id="research"', html)
                self.assertIn('id="ask"', html)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_autonomous_research_route_exposes_curiosity_questions(self):
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
                    "max_rounds": 4,
                    "max_total_sources": 12,
                }).encode("utf-8")
                req = Request(
                    base + "/api/missions/autonomous-research",
                    data=payload,
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urlopen(req, timeout=5) as response:
                    body = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 201)
                self.assertTrue(body["deep_research"]["curiosity_questions"])
                self.assertIn("stop_reason", body["deep_research"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
