import tempfile
import unittest
from pathlib import Path

from nexus1000.cognition import ContextItem, ContextManager, RecoveryController, MemoryOptimizer
from nexus1000.persistence import MemoryRecord, SQLiteStateStore


class TestSB031Cognition(unittest.TestCase):
    def test_context_keeps_essential_and_deduplicates(self):
        manager = ContextManager()
        items = [
            ContextItem("a", "old duplicate", 0.2, 0.1),
            ContextItem("b", "ESSENTIAL DECISION", 0.1, 0.1, True),
            ContextItem("c", "old duplicate", 0.9, 0.9),
            ContextItem("d", "fresh relevant context", 0.9, 0.9),
        ]
        selected = manager.select(items, max_items=3)
        texts = [x.text for x in selected]
        self.assertIn("ESSENTIAL DECISION", texts)
        self.assertEqual(len([x for x in texts if x == "old duplicate"]), 1)

    def test_recovery_returns_last_known_good_checkpoint(self):
        controller = RecoveryController()
        attempts = {"n": 0}
        def broken():
            attempts["n"] += 1
            raise RuntimeError("transient")
        result = controller.run(broken, checkpoint={"state": "known-good"}, max_retries=1)
        self.assertEqual(result.status, "RECOVERED")
        self.assertTrue(result.used_checkpoint)
        self.assertEqual(result.value["state"], "known-good")
        self.assertEqual(attempts["n"], 2)

    def test_memory_optimizer_preserves_essential_and_compacts_nonessential(self):
        with tempfile.TemporaryDirectory() as d:
            with SQLiteStateStore(Path(d) / "state.db") as store:
                for i in range(5):
                    store.put_memory(MemoryRecord(f"m{i}", "x", f"memory {i}",
                        {"essential": i == 0, "importance": 1.0 if i == 0 else 0.0, "updated_at": str(i)},
                        (1.0, 0.0)))
                optimizer = MemoryOptimizer(store)
                removed = optimizer.compact("x", keep=2)
                remaining = store.list_memory("x")
                self.assertEqual(removed, 3)
                self.assertTrue(any(m.memory_id == "m0" for m in remaining))


if __name__ == "__main__":
    unittest.main()
