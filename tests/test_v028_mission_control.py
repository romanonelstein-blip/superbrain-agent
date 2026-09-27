import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from nexus1000.mission_control import MissionControlService, ProviderUnavailableError
from nexus1000.provider_bridge import ProviderEvidence
from nexus1000.persistence import SQLiteStateStore
from nexus1000.sb022_server import build_server


def supported_evidence():
    return [
        {
            "id": "mc:orders",
            "claim": "The launch has validated demand.",
            "stance": "support",
            "source_id": "orders",
            "source_family": "commerce",
            "reliability": 0.95,
            "verified": True,
            "citation": "Commerce ledger: 240 paid preorders.",
            "content_hash": "orders-hash",
            "provider": "test",
            "provider_model": "test-v1",
            "provider_request_id": "request-1",
            "provider_agent": "research",
        },
        {
            "id": "mc:survey",
            "claim": "The launch has validated demand.",
            "stance": "support",
            "source_id": "survey",
            "source_family": "customer-research",
            "reliability": 0.95,
            "verified": True,
            "citation": "Independent survey: 82 percent intent to buy.",
            "content_hash": "survey-hash",
            "provider": "test",
            "provider_model": "test-v1",
            "provider_request_id": "request-1",
            "provider_agent": "research",
        },
     ]


def fake_provider(_mission):
    return (ProviderEvidence(
        evidence_id="provider:strategy",
        claim="Draft analysis from the strategy agent.",
        provider="openai",
        model="test-model",
        request_id="req-interactive",
        agent="strategy",
        verified=False,
        attempts=1,
        latency_ms=5,
    ),)


class TestMissionControlService(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "state.db"
        self.service = MissionControlService(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_evidence_mission_uses_canonical_runtime_and_persists_trace(self):
        result = self.service.execute_evidence_mission(
            "Should the validated-demand launch proceed?", supported_evidence(), run_id="mc-1"
        )
        self.assertEqual(result.final_value, "YES")
        self.assertEqual(result.status, "completed")
        self.assertTrue(all(result.pipeline_passes.values()))
        detail = self.service.get_mission("mc-1")
        self.assertEqual(len(detail["evidence"]), 2)
        self.assertIn("verifier", [item["stage"] for item in detail["audit"]])
        self.assertIn("final_judge", [item["stage"] for item in detail["audit"]])

    def test_interactive_mission_returns_provider_draft_and_keeps_nexus_canonical(self):
        service = MissionControlService(self.db, provider_runner=fake_provider)
        result = service.execute_interactive_mission("Explain the next priority.", run_id="interactive-1")
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.draft_responses[0]["text"], "Draft analysis from the strategy agent.")
        self.assertFalse(result.draft_responses[0]["verified"])
        detail = service.get_mission("interactive-1")
        self.assertEqual(len(detail["evidence"]), 1)
        self.assertFalse(detail["evidence"][0]["verified"])
        self.assertIn("verifier", [item["stage"] for item in detail["audit"]])

    def test_interactive_mission_without_provider_fails_clearly(self):
        service = MissionControlService(self.db, provider_runner=lambda _mission: (_ for _ in ()).throw(ProviderUnavailableError("missing provider")))
        with self.assertRaisesRegex(ProviderUnavailableError, "missing provider"):
            service.execute_interactive_mission("hello")

    def test_verified_evidence_requires_provenance(self):
        broken = supported_evidence()
        broken[0] = {**broken[0], "citation": None}
        with self.assertRaisesRegex(ValueError, "citation and content_hash"):
            self.service.execute_evidence_mission("mission", broken)

    def test_mission_and_evidence_bounds_are_enforced(self):
        with self.assertRaisesRegex(ValueError, "mission cannot be empty"):
            self.service.execute_evidence_mission("   ", supported_evidence())
        with self.assertRaisesRegex(ValueError, "at least one evidence"):
            self.service.execute_evidence_mission("mission", [])

    def test_master_decisions_are_append_only_and_do_not_overwrite_nexus_result(self):
        self.service.execute_evidence_mission("mission", supported_evidence(), run_id="mc-2")
        first = self.service.record_master_decision("mc-2", "ACCEPT", note="Proceed")
        second = self.service.record_master_decision("mc-2", "OVERRIDE", note="Hold for review", desired_outcome="NO")
        detail = self.service.get_mission("mc-2")
        self.assertEqual(detail["run"]["final_value"], "YES")
        self.assertEqual([d["action"] for d in detail["master_decisions"]], ["ACCEPT", "OVERRIDE"])
        with SQLiteStateStore(self.db) as store:
            with self.assertRaises(sqlite3.DatabaseError):
                store.conn.execute("UPDATE master_decisions SET action='REJECT' WHERE decision_id=?", (first.decision_id,))
        self.assertNotEqual(first.decision_id, second.decision_id)

    def test_invalid_master_action_is_rejected(self):
        self.service.execute_evidence_mission("mission", supported_evidence(), run_id="mc-3")
        with self.assertRaisesRegex(ValueError, "unsupported master action"):
            self.service.record_master_decision("mc-3", "AUTO_DEPLOY")

    def test_list_and_system_status(self):
        self.service.execute_evidence_mission("mission one", supported_evidence(), run_id="mc-a")
        self.service.execute_evidence_mission("mission two", supported_evidence(), run_id="mc-b")
        self.assertEqual(len(self.service.list_missions()), 2)
        status = self.service.system_status()
        self.assertEqual(status["canonical_runtime"], "NexusOrchestrator")
        self.assertFalse(status["automatic_change_application"])
        self.assertFalse(status["live_provider_validation_claimed"])
        self.assertEqual(status["ui_version"], "SB-027")
        self.assertIn("runtime_checks", status)
        self.assertIn("python", status["runtime_checks"])


class TestMissionControlHTTP(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server = build_server("127.0.0.1", 0, Path(self.tmp.name) / "server.db")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.tmp.cleanup()

    def _json(self, path, *, method="GET", body=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"} if data is not None else {}
        req = Request(self.base + path, data=data, method=method, headers=headers)
        with urlopen(req, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_health_demo_and_detail_routes(self):
        status, health = self._json("/health")
        self.assertEqual(status, 200)
        self.assertEqual(health["milestone"], "SB-027")
        self.assertEqual(health["ui_version"], "SB-027")
        status, created = self._json("/api/missions/demo", method="POST", body={})
        self.assertEqual(status, 201)
        self.assertEqual(created["final_value"], "YES")
        status, detail = self._json("/api/missions/" + created["run_id"])
        self.assertEqual(status, 200)
        self.assertEqual(detail["run"]["status"], "completed")
        self.assertEqual(len(detail["evidence"]), 2)

    def test_interactive_http_route_returns_draft_response(self):
        self.server.service.provider_runner = fake_provider
        status, created = self._json(
            "/api/missions/ask", method="POST", body={"mission": "Tell me what to do next."}
        )
        self.assertEqual(status, 201)
        self.assertEqual(created["draft_responses"][0]["agent"], "strategy")
        self.assertEqual(created["draft_responses"][0]["text"], "Draft analysis from the strategy agent.")
        status, detail = self._json("/api/missions/" + created["run_id"])
        self.assertEqual(status, 200)
        self.assertEqual(len(detail["evidence"]), 1)

    def test_static_ui_identifies_fixed_build_and_research_button(self):
        with urlopen(self.base + "/", timeout=5) as response:
            html = response.read().decode("utf-8")
        self.assertIn("SB-027", html)
        self.assertIn("Research & answer", html)
        self.assertIn("Command Center", html)
        self.assertIn("Recent missions", html)
        self.assertIn("Evidence", html)
        self.assertEqual(response.headers.get("Cache-Control"), "no-store, max-age=0")

    def test_non_loopback_requires_token(self):
        with self.assertRaisesRegex(ValueError, "requires SUPERBRAIN_MISSION_CONTROL_TOKEN"):
            build_server("0.0.0.0", 0, Path(self.tmp.name) / "unsafe.db")


if __name__ == "__main__":
    unittest.main()
