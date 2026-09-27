"""Real process termination tests; no live-provider or power-loss claims."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from nexus1000 import CheckpointStore

ROOT = Path(__file__).resolve().parents[1]
WORKER = r"""
import os
import sys
from pathlib import Path
from nexus1000 import NexusOrchestrator, StepDefinition

directory, mode = sys.argv[1:]
def record(name):
    with (Path(directory) / "calls.txt").open("a", encoding="utf-8") as stream:
        stream.write(name + "\n")
        stream.flush()
        os.fsync(stream.fileno())
def a(state):
    record("a")
    return "a-done"
def b(state):
    record("b")
    if mode == "crash":
        os._exit(73)
    if mode == "error":
        raise ValueError("temporary provider failure")
    return "b-done"
state = NexusOrchestrator().run_durable_workflow(
    "process-recovery", [StepDefinition("a", "a"), StepDefinition("b", "b")],
    {"a": a, "b": b}, directory,
)
print(state.status)
"""

class ProcessRecoveryTests(unittest.TestCase):
    def worker(self, directory, mode):
        return subprocess.run(
            [sys.executable, "-S", "-c", WORKER, directory, mode],
            cwd=ROOT, capture_output=True, text=True, timeout=20,
        )

    def test_abrupt_exit_resumes_without_repeating_completed_step(self):
        with tempfile.TemporaryDirectory() as directory:
            crashed = self.worker(directory, "crash")
            self.assertEqual(crashed.returncode, 73, crashed.stderr)
            state = CheckpointStore(directory).load("process-recovery")
            self.assertEqual(state.steps["a"].status, "completed")
            self.assertEqual(state.steps["b"].status, "running")
            resumed = self.worker(directory, "resume")
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            self.assertEqual(resumed.stdout.strip(), "completed")
            state = CheckpointStore(directory).load("process-recovery")
            self.assertEqual(state.steps["b"].attempts, 2)
            self.assertEqual(state.steps["b"].result, "b-done")
            # A further fresh process must not replay completed handlers.
            again = self.worker(directory, "resume")
            self.assertEqual(again.returncode, 0, again.stderr)
            self.assertEqual(again.stdout.strip(), "completed")
            self.assertEqual((Path(directory) / "calls.txt").read_text().splitlines(),
                             ["a", "b", "b"])

    def test_repeated_crashes_do_not_reset_persisted_retry_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            for _ in range(3):
                crashed = self.worker(directory, "crash")
                self.assertEqual(crashed.returncode, 73, crashed.stderr)
            resumed = self.worker(directory, "resume")
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            self.assertEqual(resumed.stdout.strip(), "failed")
            state = CheckpointStore(directory).load("process-recovery")
            self.assertEqual(state.steps["b"].attempts, 3)
            self.assertEqual(state.steps["b"].status, "failed")
            self.assertEqual((Path(directory) / "calls.txt").read_text().splitlines(),
                             ["a", "b", "b", "b"])

    def test_crash_then_retryable_errors_share_one_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(self.worker(directory, "crash").returncode, 73)
            failed = self.worker(directory, "error")
            self.assertEqual(failed.returncode, 0, failed.stderr)
            self.assertEqual(failed.stdout.strip(), "failed")
            state = CheckpointStore(directory).load("process-recovery")
            self.assertEqual(state.steps["b"].attempts, 3)
            self.assertIn("temporary provider failure", state.steps["b"].error)
            # A third process must preserve terminal exhaustion, even if the
            # provider would now succeed.
            resumed = self.worker(directory, "resume")
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            self.assertEqual(resumed.stdout.strip(), "failed")
            self.assertEqual((Path(directory) / "calls.txt").read_text().splitlines(),
                             ["a", "b", "b", "b"])

if __name__ == "__main__":
    unittest.main()
