import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen

from nexus1000.mission_control import MissionControlService
from nexus1000.models import Stance
from nexus1000.research import RetrievedResearchSource, SearchHit
from nexus1000.sb022_server import build_server
from nexus1000.world_model import BeliefState, WorldModel


def evidence_item(evidence_id: str, source_id: str, family: str, stance: str) -> dict:
    return {
        "id": evidence_id,
        "claim": f"Evidence {evidence_id}",
        "stance": stance,
        "source_id": source_id,
        "source_family": family,
        "reliability": 1.0,
        "freshness": 1.0,
        "relevance": 1.0,
        "verified": True,
        "citation": f"https://{family}/source",
        "content_hash": hashlib.sha256(evidence_id.encode()).hexdigest(),
        "retrieved_at": "2026-09-21T00:00:00+00:00",
        "location": f"https://{family}/source",
        "content_type": "text/html",
    }


class TestSB027WorldModel(unittest.TestCase):
    def test_revision_accumulates_support_and_then_challenge(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = MissionControlService(Path(temporary) / "state.db")
            mission = "Should the evidence-backed launch proceed?"
            first = service.execute_evidence_mission(
                mission,
                [
                    evidence_item("support-a", "a", "a.example", "support"),
                    evidence_item("support-b", "b", "b.example", "support"),
                    evidence_item("support-c", "c", "c.example", "support"),
                    evidence_item("support-d", "d", "d.example", "support"),
                ],
                run_id="sb027-support",
            )
            self.assertEqual(first.status, "completed")
            detail = service.get_mission("sb027-support")
            self.assertEqual(detail["world_model"]["state"], BeliefState.SUPPORTED.value)
            self.assertEqual(detail["world_model"]["evidence_count"], 4)
            self.assertIn("world_model", [item["stage"] for item in detail["audit"]])

            second = service.execute_evidence_mission(
                mission,
                [
                    evidence_item("challenge-a", "ca", "challenge-a.example", "challenge"),
                    evidence_item("challenge-b", "cb", "challenge-b.example", "challenge"),
                    evidence_item("challenge-c", "cc", "challenge-c.example", "challenge"),
                    evidence_item("challenge-d", "cd", "challenge-d.example", "challenge"),
                ],
                run_id="sb027-challenge",
            )
            self.assertEqual(second.status, "completed")
            beliefs = service.list_world_beliefs()
            self.assertEqual(len(beliefs), 1)
            belief = beliefs[0]
            self.assertEqual(belief["state"], BeliefState.CONTESTED.value)
            self.assertEqual(belief["evidence_count"], 8)
            self.assertGreaterEqual(belief["revision_count"], 1)
            self.assertEqual(belief["unique_family_count"], 8)

    def test_normalization_is_deterministic(self):
        a = WorldModel.normalize_proposition("  HELLO,   World!  ")
        b = WorldModel.normalize_proposition("hello world")
        self.assertEqual(a, b)
        self.assertEqual(WorldModel.belief_id_for(a), WorldModel.belief_id_for(b))


class TestSB027OSINTDiagnostics(unittest.TestCase):
    def test_diagnostics_never_exposes_credentials(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            "os.environ", {"SUPERBRAIN_RESEARCH_SOURCES": "github,duckduckgo"}, clear=False
        ), patch("nexus1000.mission_control.detect_local_tor_proxy", return_value=None), patch(
            "nexus1000.mission_control.GitHubSearchClient.search", return_value=(
                SearchHit("repo", "https://github.com/example/repo", "repo", "github", 1, "openai", Stance.NEUTRAL),
            )
        ), patch(
            "nexus1000.mission_control.DuckDuckGoSearchClient.search", return_value=(
                SearchHit("ddg", "https://example.com/", "example", "duckduckgo", 1, "DuckDuckGo", Stance.NEUTRAL),
            )
        ), patch(
            "nexus1000.mission_control.SafeResearchSourceFetcher.fetch",
            return_value=RetrievedResearchSource(
                "source", "example.com", "example", "https://example.com/", "text",
                hashlib.sha256(b"text").hexdigest(), "2026-09-21T00:00:00+00:00", "text/html",
                "query", Stance.NEUTRAL, "fixture", 1,
            ),
        ):
            service = MissionControlService(Path(temporary) / "state.db")
            result = service.run_osint_diagnostics()
        self.assertEqual(result["overall"], "PASS")
        self.assertFalse(result["credential_values_exposed"])
        self.assertEqual({item["provider"] for item in result["providers"]}, {"github", "duckduckgo", "tor"})


class TestSB027HTTP(unittest.TestCase):
    def test_dashboard_and_world_model_endpoint(self):
        with tempfile.TemporaryDirectory() as temporary:
            server = build_server("127.0.0.1", 0, Path(temporary) / "state.db")
            server.service.execute_evidence_mission(
                "Can the dashboard track beliefs?",
                [evidence_item("e1", "s1", "s1.example", "support"), evidence_item("e2", "s2", "s2.example", "support")],
                run_id="sb027-http-belief",
            )
            server.service.run_osint_diagnostics = lambda: {
                "overall": "PASS", "providers": [], "onion": {"status": "POLICY_ONLY"}, "credential_values_exposed": False
            }
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                with urlopen(base + "/", timeout=5) as response:
                    html = response.read().decode("utf-8")
                self.assertIn("SB-027 · WORLD MODEL + OSINT", html)
                self.assertIn('id="osint-diagnostics"', html)
                self.assertIn('id="world-model-list"', html)

                with urlopen(base + "/api/world-model?limit=10", timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
                self.assertEqual(len(payload["beliefs"]), 1)

                request = Request(
                    base + "/api/osint/diagnostics",
                    data=b"{}",
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urlopen(request, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
                self.assertEqual(payload["overall"], "PASS")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
