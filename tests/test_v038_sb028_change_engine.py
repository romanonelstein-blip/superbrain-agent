import hashlib
import tempfile
import unittest
from pathlib import Path
from urllib.request import urlopen
import json
import threading

from nexus1000.mission_control import MissionControlService
from nexus1000.sb022_server import build_server
from nexus1000.world_model import BeliefState


def ev(eid, stance):
    return {
        "id": eid, "claim": f"Claim {eid}", "stance": stance,
        "source_id": eid, "source_family": eid + ".example",
        "reliability": 1.0, "freshness": 1.0, "relevance": 1.0,
        "verified": True, "citation": f"https://{eid}.example/source",
        "content_hash": hashlib.sha256(eid.encode()).hexdigest(),
    }


class TestSB028ChangeEngine(unittest.TestCase):
    def test_material_change_is_persisted(self):
        with tempfile.TemporaryDirectory() as d:
            service = MissionControlService(Path(d) / "state.db")
            mission = "Should the launch proceed?"
            service.execute_evidence_mission(mission, [ev("s1", "support"), ev("s2", "support"), ev("s3", "support"), ev("s4", "support")], run_id="r1")
            service.execute_evidence_mission(mission, [ev("c1", "challenge"), ev("c2", "challenge"), ev("c3", "challenge"), ev("c4", "challenge")], run_id="r2")
            changes = service.list_changes()
            self.assertGreaterEqual(len(changes), 2)
            self.assertEqual(changes[-1]["event_type"], "SUPPORTED")
            self.assertEqual(changes[0]["event_type"], "CONTESTED")
            self.assertEqual(changes[0]["severity"], "HIGH")

    def test_change_api(self):
        with tempfile.TemporaryDirectory() as d:
            server = build_server("127.0.0.1", 0, Path(d) / "state.db")
            server.service.execute_evidence_mission("Track this", [ev("a", "support"), ev("b", "support"), ev("c", "support"), ev("d", "support")], run_id="api-r1")
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                with urlopen(base + "/api/changes?limit=10", timeout=5) as response:
                    payload = json.loads(response.read().decode())
                self.assertEqual(response.status, 200)
                self.assertTrue(payload["changes"])
            finally:
                server.shutdown(); server.server_close(); thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
