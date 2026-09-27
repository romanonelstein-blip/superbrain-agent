import tempfile
import unittest
from pathlib import Path

from nexus1000.persistence import RunRecord, SQLiteStateStore
from nexus1000.scheduler import DurableAutonomyScheduler, SchedulerPolicy


class Clock:
    def __init__(self, value=1000.0):
        self.value = value

    def __call__(self):
        return self.value


class FakeService:
    def __init__(self, db):
        self.database_path = db
        self.calls = []

    def execute_deep_research_mission(self, mission, *, run_id, max_rounds, max_total_sources):
        self.calls.append((mission, run_id))
        return type("R", (), {"nexus_final_value": "YES", "research": {"stop_reason": "sufficient"}})()

    def get_mission(self, run_id):
        return {
            "run": {"final_value": "YES"},
            "evidence": [{
                "stance": "support",
                "source_id": "s1",
                "source_family": "f1",
                "reliability": 0.9,
                "freshness": 1.0,
                "relevance": 1.0,
                "citation": "https://example.test/evidence",
                "content_hash": "abc",
            }],
            "world_model": {"state": "SUPPORTED", "confidence": 0.9},
        }

    def run_assurance(self, observation, *, run_id):
        return {"status": "PASS", "score": 1.0}

    def list_changes(self, limit=100):
        return []


class TestP0Durability(unittest.TestCase):
    def test_sqlite_backup_restore_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "state.db"
            backup = Path(d) / "backup.db"
            with SQLiteStateStore(db) as store:
                store.upsert_run(RunRecord("r1", "completed", "one", "t1", "t1", "YES"))
                store.backup_to(backup)
                store.upsert_run(RunRecord("r2", "completed", "two", "t2", "t2", "NO"))
                self.assertIsNotNone(store.get_run("r2"))
                store.restore_from(backup)
                ok, detail = store.integrity_check()
                self.assertTrue(ok, detail)
                self.assertIsNotNone(store.get_run("r1"))
                self.assertIsNone(store.get_run("r2"))

    def test_scheduler_state_survives_process_recreation(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "state.db"
            clock = Clock()
            service = FakeService(db)
            policy = SchedulerPolicy(interval_seconds=30, failure_backoff_seconds=5, max_backoff_seconds=60)

            first = DurableAutonomyScheduler(service, policy=policy, clock=clock)
            first.ensure_configured(start_immediately=True)
            run1 = first.run_due(["A"])
            self.assertTrue(run1["ok"])
            state1 = first.status()
            self.assertEqual(state1["next_run_at"], 1030.0)

            # Simulate a process restart by constructing a brand-new scheduler.
            restarted = DurableAutonomyScheduler(service, policy=policy, clock=clock)
            self.assertEqual(restarted.status()["last_cycle_id"], state1["last_cycle_id"])
            self.assertEqual(restarted.status()["next_run_at"], 1030.0)
            self.assertFalse(restarted.run_due(["A"])["ran"])

            clock.value = 1031.0
            run2 = restarted.run_due(["A"])
            self.assertTrue(run2["ok"])
            self.assertEqual(restarted.status()["next_run_at"], 1061.0)
            self.assertEqual(len(service.calls), 2)

    def test_scheduler_failure_is_persisted_with_backoff(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "state.db"
            clock = Clock()
            service = FakeService(db)
            service.execute_deep_research_mission = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("provider offline"))
            scheduler = DurableAutonomyScheduler(
                service,
                policy=SchedulerPolicy(interval_seconds=30, failure_backoff_seconds=5, max_backoff_seconds=60),
                clock=clock,
            )
            scheduler.ensure_configured(start_immediately=True)
            result = scheduler.run_due(["A"])
            self.assertFalse(result["ok"])
            state = scheduler.status()
            self.assertEqual(state["consecutive_failures"], 1)
            self.assertIn("blocked", state["last_error"])
            self.assertEqual(state["next_run_at"], 1005.0)


if __name__ == "__main__":
    unittest.main()
