import sqlite3
import tempfile
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

from nexus1000.evals import NexusGoldenExecutor
from nexus1000.experiments import (
    ExperimentArtifact,
    ExperimentCandidate,
    ExperimentEngine,
    SQLiteExperimentStore,
)


ROOT = Path(__file__).resolve().parents[1]


def candidate(status: str = "PROPOSED") -> ExperimentCandidate:
    return ExperimentCandidate(
        candidate_id="candidate-calibration-v1",
        description="Improve calibration without changing decisions or evidence gates.",
        status=status,
        artifacts=(
            ExperimentArtifact(
                "candidate.json",
                b'{"kind":"calibration-only","version":1}',
                "application/json",
            ),
        ),
    )


class CanonicalExperimentExecutor:
    executor_id = "canonical-experiment"

    def __init__(self):
        self.delegate = NexusGoldenExecutor()
        self.task_ids = []

    def execute(self, task, sandbox):
        self.task_ids.append(task.task_id)
        self.asserted_artifact = sandbox.read_candidate_artifact("candidate.json")
        sandbox.write_output_artifact(
            f"tasks/{task.task_id}.txt",
            f"evaluated:{task.task_id}".encode("utf-8"),
            "text/plain",
        )
        return self.delegate.execute(task)


class CalibrationExperimentExecutor(CanonicalExperimentExecutor):
    executor_id = "calibration-experiment"

    def execute(self, task, sandbox):
        result = super().execute(task, sandbox)
        probability = result.yes_probability if result.predicted_result == "YES" else 0.20
        return replace(result, yes_probability=probability)


class RegressionExperimentExecutor(CanonicalExperimentExecutor):
    executor_id = "regression-experiment"

    def execute(self, task, sandbox):
        result = super().execute(task, sandbox)
        if task.task_id == "verified-diverse-support":
            result = replace(result, predicted_result="NO", yes_probability=0.10)
        return replace(result, cost_units=result.cost_units + 2.0, latency_ms=result.latency_ms + 100.0)


class MutationAttemptExecutor(CanonicalExperimentExecutor):
    executor_id = "mutation-attempt"

    def __init__(self):
        super().__init__()
        self.task_is_frozen = False
        self.contract_not_exposed = False
        self.escape_blocked = False

    def execute(self, task, sandbox):
        try:
            task.mission = "mutated"
        except FrozenInstanceError:
            self.task_is_frozen = True
        self.contract_not_exposed = not hasattr(sandbox, "suite") and not hasattr(sandbox, "policy")
        try:
            sandbox.write_output_artifact("../escape.txt", b"blocked")
        except ValueError:
            self.escape_blocked = True
        return super().execute(task, sandbox)


class TestExperimentEngine(unittest.TestCase):
    def _engine(self, root: Path, store: SQLiteExperimentStore) -> ExperimentEngine:
        return ExperimentEngine(
            golden_tasks_path=ROOT / "evals" / "golden_tasks.json",
            baseline_path=ROOT / "evals" / "golden_baseline.json",
            store=store,
            sandbox_root=root / "sandboxes",
        )

    def test_no_improvement_is_logged_without_applying_anything(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with SQLiteExperimentStore(root / "experiments.db") as store:
                executor = CanonicalExperimentExecutor()
                result = self._engine(root, store).run(candidate(), executor)

                self.assertEqual(result.decision, "NO_IMPROVEMENT")
                self.assertFalse(result.automatic_change_applied)
                self.assertEqual(len(executor.task_ids), 5)
                self.assertEqual(executor.asserted_artifact, candidate().artifacts[0].content)
                persisted = store.get_experiment(result.experiment_id)
                self.assertEqual(persisted.decision, "NO_IMPROVEMENT")
                self.assertFalse(persisted.automatic_change_applied)
                self.assertIsNotNone(persisted.baseline_report)
                self.assertIsNotNone(persisted.candidate_report)

    def test_measurable_calibration_improvement_is_only_eligible_for_approval(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with SQLiteExperimentStore(root / "experiments.db") as store:
                result = self._engine(root, store).run(
                    candidate(),
                    CalibrationExperimentExecutor(),
                )

                self.assertEqual(result.decision, "ELIGIBLE_FOR_APPROVAL")
                self.assertTrue(result.requires_explicit_approval)
                self.assertFalse(result.automatic_change_applied)
                self.assertGreater(
                    result.candidate_metrics.calibration_score,
                    result.baseline_metrics.calibration_score,
                )

    def test_regression_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with SQLiteExperimentStore(root / "experiments.db") as store:
                result = self._engine(root, store).run(candidate(), RegressionExperimentExecutor())

                self.assertEqual(result.decision, "REJECT")
                self.assertFalse(result.requires_explicit_approval)
                self.assertFalse(result.automatic_change_applied)
                self.assertTrue(any("accuracy" in item for item in result.regressions))
                self.assertTrue(any("cost" in item for item in result.regressions))

    def test_candidate_cannot_mutate_tasks_contract_or_escape_output_area(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with SQLiteExperimentStore(root / "experiments.db") as store:
                executor = MutationAttemptExecutor()
                result = self._engine(root, store).run(candidate(), executor)

                self.assertEqual(result.decision, "NO_IMPROVEMENT")
                self.assertTrue(executor.task_is_frozen)
                self.assertTrue(executor.contract_not_exposed)
                self.assertTrue(executor.escape_blocked)
                self.assertFalse((root / "escape.txt").exists())

    def test_candidate_and_contract_artifacts_are_content_addressed_and_persisted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "experiments.db"
            with SQLiteExperimentStore(database) as store:
                result = self._engine(root, store).run(candidate(), CanonicalExperimentExecutor())
                artifacts = store.list_artifacts(result.experiment_id)
                roles = {item.role for item in artifacts}
                self.assertEqual(roles, {"CANDIDATE", "CONTRACT", "OUTPUT", "REPORT"})
                self.assertTrue(all(len(item.sha256) == 64 for item in artifacts))
                self.assertTrue(any(item.relative_path == "golden_tasks.json" for item in artifacts))
                self.assertTrue(any(item.relative_path == "candidate.json" for item in artifacts))

            with SQLiteExperimentStore(database) as reopened:
                persisted = reopened.get_experiment(result.experiment_id)
                self.assertEqual(persisted.snapshot_digest, result.snapshot_digest)
                self.assertEqual(len(reopened.list_events(result.experiment_id)), len(result.trace))

    def test_persisted_snapshot_artifacts_and_completed_record_are_immutable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with SQLiteExperimentStore(root / "experiments.db") as store:
                result = self._engine(root, store).run(candidate(), CanonicalExperimentExecutor())
                with self.assertRaises(sqlite3.IntegrityError):
                    store.conn.execute(
                        "UPDATE experiments SET snapshot_json = '{}' WHERE experiment_id = ?",
                        (result.experiment_id,),
                    )
                with self.assertRaises(sqlite3.IntegrityError):
                    store.conn.execute(
                        "UPDATE experiment_artifacts SET content = X'00' WHERE experiment_id = ?",
                        (result.experiment_id,),
                    )
                with self.assertRaises(sqlite3.IntegrityError):
                    store.conn.execute(
                        "DELETE FROM experiments WHERE experiment_id = ?",
                        (result.experiment_id,),
                    )
                with self.assertRaises(sqlite3.IntegrityError):
                    store.conn.execute(
                        """
                        INSERT INTO experiment_events (
                            experiment_id, stage, detail, occurred_at
                        ) VALUES (?, 'late', 'blocked', '2026-09-20T00:00:00+00:00')
                        """,
                        (result.experiment_id,),
                    )

    def test_non_proposed_candidate_is_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with SQLiteExperimentStore(root / "experiments.db") as store:
                executor = CanonicalExperimentExecutor()
                with self.assertRaisesRegex(ValueError, "PROPOSED"):
                    self._engine(root, store).run(candidate("APPROVED"), executor)
                self.assertEqual(executor.task_ids, [])
                self.assertEqual(store.list_experiments(), ())

    def test_executor_failure_is_persisted_and_never_applied(self):
        class FailingExecutor:
            executor_id = "failing"

            def execute(self, task, sandbox):
                raise RuntimeError("candidate failure")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with SQLiteExperimentStore(root / "experiments.db") as store:
                with self.assertRaisesRegex(RuntimeError, "candidate failure"):
                    self._engine(root, store).run(candidate(), FailingExecutor())
                persisted = store.list_experiments()[0]
                self.assertEqual(persisted.status, "FAILED")
                self.assertFalse(persisted.automatic_change_applied)
                self.assertIn("candidate failure", persisted.error)

    def test_quality_workflow_runs_sb019_acceptance(self):
        workflow = (ROOT / ".github" / "workflows" / "sb018-quality.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn('"experiments/**"', workflow)
        self.assertIn("python -m nexus1000.sb019_experiment", workflow)


if __name__ == "__main__":
    unittest.main()
