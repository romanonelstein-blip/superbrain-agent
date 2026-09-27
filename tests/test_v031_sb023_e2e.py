import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from nexus1000.mission_control import MissionControlService
from nexus1000.models import Stance
from nexus1000.provider_bridge import ProviderEvidence
from nexus1000.research import ResearchEngine, RetrievedResearchSource, SearchHit
from nexus1000.sb022_server import build_server


class Search:
    name = "acceptance-search"

    def search(self, query, limit):
        if "counterevidence" in query:
            return ()
        return (
            SearchHit("Source A", "https://a.example/article", "A", self.name, 1, query, Stance.NEUTRAL),
            SearchHit("Source B", "https://b.example/article", "B", self.name, 2, query, Stance.NEUTRAL),
        )[:limit]


class Fetcher:
    def fetch(self, hit):
        host = hit.url.split("/")[2]
        return RetrievedResearchSource(
            source_id="source-" + host,
            source_family=host,
            title=hit.title,
            url=hit.url,
            excerpt=f"Independent published evidence from {host} supports the tested proposition.",
            content_hash=(host.replace(".", "") + "0" * 64)[:64],
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
            evidence_id="synthesis:strategy",
            claim="The retrieved sources support proceeding, with the stated evidence limitations.",
            provider="openai",
            model="fixture",
            request_id="synthesis-1",
            agent="strategy",
            verified=False,
            attempts=1,
            latency_ms=1,
        ),
    )


class TestSB023EndToEnd(unittest.TestCase):
    def test_research_mission_retrieves_sources_runs_nexus_and_returns_synthesis(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = MissionControlService(
                Path(temporary) / "state.db",
                research_engine=ResearchEngine(Search(), source_fetcher=Fetcher()),
                research_synthesizer=synthesize,
            )
            result = service.execute_research_mission(
                "Should the evidence-backed launch proceed?",
                run_id="sb023-e2e",
            )
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.nexus_final_value, "YES")
            self.assertTrue(all(result.pipeline_passes.values()))
            self.assertEqual(result.evidence_count, 2)
            self.assertEqual(len(result.research["sources"]), 2)
            self.assertEqual(result.draft_responses[0]["agent"], "strategy")

            detail = service.get_mission("sb023-e2e")
            self.assertTrue(all(item["verified"] for item in detail["evidence"]))
            stages = [item["stage"] for item in detail["audit"]]
            self.assertEqual(stages[:3], ["research_plan", "web_search", "source_retrieval"])
            self.assertIn("verifier", stages)


class TestSB023HTTP(unittest.TestCase):
    def test_research_route_returns_sources_and_synthesis(self):
        with tempfile.TemporaryDirectory() as temporary:
            server = build_server("127.0.0.1", 0, Path(temporary) / "state.db")
            server.service.research_engine = ResearchEngine(Search(), source_fetcher=Fetcher())
            server.service.research_synthesizer = synthesize
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                payload = json.dumps({"mission": "Should the evidence-backed launch proceed?"}).encode("utf-8")
                req = Request(
                    base + "/api/missions/research",
                    data=payload,
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urlopen(req, timeout=5) as response:
                    body = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 201)
                self.assertEqual(body["nexus_final_value"], "YES")
                self.assertEqual(len(body["research"]["sources"]), 2)
                self.assertEqual(body["draft_responses"][0]["agent"], "strategy")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
