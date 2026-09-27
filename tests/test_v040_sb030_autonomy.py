import tempfile
import unittest
from pathlib import Path

from nexus1000.autonomy import AutonomousIntelligenceEngine, AutonomyPolicy
from nexus1000.persistence import SQLiteStateStore


class FakeService:
    def __init__(self, db):
        self.database_path = db
        self.calls = []

    def execute_deep_research_mission(self, mission, *, run_id, max_rounds, max_total_sources):
        self.calls.append((mission, run_id, max_rounds, max_total_sources))
        return type("R", (), {"nexus_final_value": "YES", "research": {"stop_reason": "sufficient"}})()

    def get_mission(self, run_id):
        return {
            "run": {"final_value": "YES"},
            "evidence": [{
                "stance": "support", "source_id": "s1", "source_family": "f1",
                "reliability": 0.9, "freshness": 1.0, "relevance": 1.0,
                "citation": "https://example.test/evidence", "content_hash": "abc",
            }],
            "world_model": {"state": "SUPPORTED", "confidence": 0.9},
        }

    def run_assurance(self, observation, *, run_id):
        return {"status": "PASS", "score": 1.0}

    def list_changes(self, limit=100):
        return []


class TestSB030Autonomy(unittest.TestCase):
    def test_bounded_cycle_executes_and_persists(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "state.db"
            service = FakeService(db)
            engine = AutonomousIntelligenceEngine(service, policy=AutonomyPolicy(max_missions_per_cycle=2))
            result = engine.run_cycle(["Determine whether proposition A is supported"], cycle_id="cycle-a")
            self.assertEqual(result.status, "COMPLETED")
            self.assertEqual(len(result.steps), 1)
            self.assertEqual(result.steps[0].assurance_status, "PASS")
            with SQLiteStateStore(db) as store:
                rows = store.list_autonomy_cycles()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["cycle_id"], "cycle-a")

    def test_assurance_failure_blocks_continuation(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "state.db"
            service = FakeService(db)
            service.run_assurance = lambda observation, *, run_id: {"status": "FAIL", "score": 0.4}
            engine = AutonomousIntelligenceEngine(service, policy=AutonomyPolicy(max_missions_per_cycle=2, min_assurance_score=0.7))
            result = engine.run_cycle(["A", "B"], cycle_id="cycle-b")
            self.assertEqual(result.status, "BLOCKED")
            self.assertEqual(len(result.steps), 1)
            self.assertIn("ESCALATE_TO_MASTER", result.next_actions)

    def test_no_work_is_safe(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "state.db"
            service = FakeService(db)
            engine = AutonomousIntelligenceEngine(service)
            result = engine.run_cycle([], cycle_id="cycle-c")
            self.assertEqual(result.status, "NO_WORK")
            self.assertEqual(result.steps, ())


if __name__ == "__main__":
    unittest.main()
