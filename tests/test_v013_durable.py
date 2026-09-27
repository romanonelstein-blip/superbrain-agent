import tempfile
import unittest
from pathlib import Path

from nexus1000 import (
    CheckpointStore,
    DurableWorkflow,
    IdempotencyLedger,
    RetryPolicy,
    StepDefinition,
    NexusOrchestrator,
)


class TestCheckpointStore(unittest.TestCase):
    def test_state_is_persisted_and_reloaded(self):
        with tempfile.TemporaryDirectory() as td:
            store = CheckpointStore(td)
            wf = DurableWorkflow(
                "run1",
                [StepDefinition("a", "a-key")],
                store,
            )
            state = wf.run({"a": lambda s: "ok"})
            loaded = store.load("run1")
            self.assertEqual(state.status, "completed")
            self.assertEqual(loaded.status, "completed")
            self.assertEqual(loaded.steps["a"].result, "ok")


class TestResume(unittest.TestCase):
    def test_resume_skips_completed_steps_after_crash(self):
        with tempfile.TemporaryDirectory() as td:
            store = CheckpointStore(td)
            calls = {"a": 0, "b": 0, "c": 0}
            steps = [
                StepDefinition("a", "key-a"),
                StepDefinition("b", "key-b"),
                StepDefinition("c", "key-c"),
            ]

            def make(name):
                def f(state):
                    calls[name] += 1
                    return f"{name}-done"
                return f

            handlers = {x: make(x) for x in calls}

            wf1 = DurableWorkflow("run", steps, store)
            with self.assertRaises(RuntimeError):
                wf1.run(handlers, crash_after_step="b")

            self.assertEqual(calls, {"a": 1, "b": 1, "c": 0})

            wf2 = DurableWorkflow("run", steps, store)
            state = wf2.run(handlers)

            self.assertEqual(state.status, "completed")
            self.assertEqual(calls, {"a": 1, "b": 1, "c": 1})

    def test_completed_workflow_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            store = CheckpointStore(td)
            count = {"n": 0}

            def handler(state):
                count["n"] += 1
                return "x"

            steps = [StepDefinition("a", "same-key")]
            DurableWorkflow("run", steps, store).run({"a": handler})
            DurableWorkflow("run", steps, store).run({"a": handler})

            self.assertEqual(count["n"], 1)


class TestRetries(unittest.TestCase):
    def test_retryable_failure_recovers(self):
        with tempfile.TemporaryDirectory() as td:
            store = CheckpointStore(td)
            attempts = {"n": 0}

            def flaky(state):
                attempts["n"] += 1
                if attempts["n"] < 3:
                    raise ValueError("temporary")
                return "ok"

            steps = [
                StepDefinition(
                    "a",
                    "key-a",
                    RetryPolicy(
                        max_attempts=3,
                        initial_backoff_seconds=0,
                        retryable_exceptions=(ValueError,),
                    ),
                )
            ]

            state = DurableWorkflow("run", steps, store).run({"a": flaky})
            self.assertEqual(state.status, "completed")
            self.assertEqual(attempts["n"], 3)
            self.assertEqual(state.steps["a"].attempts, 3)

    def test_retry_budget_exhaustion_fails(self):
        with tempfile.TemporaryDirectory() as td:
            store = CheckpointStore(td)

            def bad(state):
                raise ValueError("still broken")

            steps = [
                StepDefinition(
                    "a",
                    "key-a",
                    RetryPolicy(
                        max_attempts=2,
                        initial_backoff_seconds=0,
                        retryable_exceptions=(ValueError,),
                    ),
                )
            ]

            state = DurableWorkflow("run", steps, store).run({"a": bad})
            self.assertEqual(state.status, "failed")
            self.assertEqual(state.steps["a"].attempts, 2)

    def test_non_retryable_failure_stops_immediately(self):
        with tempfile.TemporaryDirectory() as td:
            store = CheckpointStore(td)

            def bad(state):
                raise TypeError("fatal")

            steps = [
                StepDefinition(
                    "a",
                    "key-a",
                    RetryPolicy(
                        max_attempts=5,
                        initial_backoff_seconds=0,
                        retryable_exceptions=(ValueError,),
                    ),
                )
            ]

            state = DurableWorkflow("run", steps, store).run({"a": bad})
            self.assertEqual(state.status, "failed")
            self.assertEqual(state.steps["a"].attempts, 1)


class TestSafetyAndIntegrity(unittest.TestCase):
    def test_missing_handler_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as td:
            state = DurableWorkflow(
                "run",
                [StepDefinition("a", "a")],
                CheckpointStore(td),
            ).run({})
            self.assertEqual(state.status, "failed")
            self.assertEqual(state.steps["a"].error, "missing handler")

    def test_checkpoint_after_every_attempt(self):
        with tempfile.TemporaryDirectory() as td:
            store = CheckpointStore(td)
            attempts = {"n": 0}

            def bad(state):
                attempts["n"] += 1
                raise ValueError("x")

            steps = [
                StepDefinition(
                    "a",
                    "a",
                    RetryPolicy(max_attempts=2, retryable_exceptions=(ValueError,)),
                )
            ]
            DurableWorkflow("run", steps, store).run({"a": bad})
            loaded = store.load("run")
            self.assertEqual(loaded.steps["a"].attempts, 2)
            self.assertEqual(loaded.steps["a"].status, "failed")

    def test_atomic_checkpoint_file_exists_without_tmp_residue(self):
        with tempfile.TemporaryDirectory() as td:
            store = CheckpointStore(td)
            DurableWorkflow(
                "run",
                [StepDefinition("a", "a")],
                store,
            ).run({"a": lambda s: "ok"})
            files = sorted(p.name for p in Path(td).iterdir())
            self.assertEqual(files, ["run.json"])


class TestOrchestratorIntegration(unittest.TestCase):
    def test_orchestrator_can_resume_durable_run(self):
        with tempfile.TemporaryDirectory() as td:
            orch = NexusOrchestrator()
            calls = {"a": 0, "b": 0}

            steps = [
                StepDefinition("a", "a"),
                StepDefinition("b", "b"),
            ]

            def a(state):
                calls["a"] += 1
                return 1

            def b(state):
                calls["b"] += 1
                return 2

            with self.assertRaises(RuntimeError):
                orch.run_durable_workflow(
                    "r1",
                    steps,
                    {"a": a, "b": b},
                    td,
                    crash_after_step="a",
                )

            state = orch.run_durable_workflow(
                "r1",
                steps,
                {"a": a, "b": b},
                td,
            )

            self.assertEqual(state.status, "completed")
            self.assertEqual(calls, {"a": 1, "b": 1})
            stages = [e.stage for e in orch.timeline.events]
            self.assertIn("workflow_crash", stages)
            self.assertIn("workflow", stages)


if __name__ == "__main__":
    unittest.main()
