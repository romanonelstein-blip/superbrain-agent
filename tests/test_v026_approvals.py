from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from nexus1000.approvals import (
    APPROVAL_INTENT,
    ApprovalGatedApplyEngine,
    HumanApprovalSigner,
    SQLiteApplyStore,
)
from nexus1000.evals import NexusGoldenExecutor
from nexus1000.experiments import (
    ExperimentArtifact,
    ExperimentCandidate,
    ExperimentEngine,
    SQLiteExperimentStore,
)


ROOT = Path(__file__).resolve().parents[1]
SECRET = b"human-controlled-test-key-material-32-bytes-minimum"


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class CalibrationExecutor:
    executor_id = "sb020-candidate"

    def __init__(self, probability: float = 0.20):
        self.delegate = NexusGoldenExecutor()
        self.probability = probability

    def execute(self, task, sandbox=None):
        value = self.delegate.execute(task)
        if sandbox is not None:
            sandbox.read_candidate_artifact("apply-plan.json")
        return replace(
            value,
            yes_probability=value.yes_probability if value.predicted_result == "YES" else self.probability,
        )


def executor_factory(workspace: Path):
    payload = json.loads((workspace / "runtime-policy.json").read_text(encoding="utf-8"))
    return CalibrationExecutor(float(payload["negative_yes_probability"]))


class ApplyFixture:
    def __init__(self, root: Path, replacement_probability: float = 0.20):
        self.root = root
        self.workspace = root / "workspace"
        self.workspace.mkdir()
        self.target = self.workspace / "runtime-policy.json"
        self.original = b'{"negative_yes_probability": 0.49}'
        self.target.write_bytes(self.original)
        plan = {
            "schema_version": "sb020.apply.v1",
            "operations": [{
                "op": "replace",
                "path": "runtime-policy.json",
                "source_artifact": "payload/runtime-policy.json",
                "expected_before_sha256": digest(self.original),
            }],
        }
        self.experiment_db = root / "experiments.db"
        self.apply_db = root / "approvals.db"
        self.experiments = SQLiteExperimentStore(self.experiment_db)
        candidate = ExperimentCandidate(
            "candidate-sb020", "Apply calibrated confidence policy.", "PROPOSED",
            (
                ExperimentArtifact("apply-plan.json", json.dumps(plan, sort_keys=True).encode(), "application/json"),
                ExperimentArtifact(
                    "payload/runtime-policy.json",
                    json.dumps({"negative_yes_probability": replacement_probability}, sort_keys=True).encode(),
                    "application/json",
                ),
            ),
        )
        self.experiment = ExperimentEngine(
            golden_tasks_path=ROOT / "evals" / "golden_tasks.json",
            baseline_path=ROOT / "evals" / "golden_baseline.json",
            store=self.experiments,
            sandbox_root=root / "sandboxes",
        ).run(candidate, CalibrationExecutor())
        self.applies = SQLiteApplyStore(self.apply_db)
        self.signer = HumanApprovalSigner(SECRET)
        stored = self.experiments.get_experiment(self.experiment.experiment_id)
        self.approval = self.signer.issue(
            experiment_id=stored.experiment_id,
            snapshot_digest=stored.snapshot_digest,
            candidate_id=stored.candidate_id,
            suite_digest=stored.snapshot["suite_digest"],
            approver_id="human:test-owner",
            intent=APPROVAL_INTENT,
        )
        self.engine = ApprovalGatedApplyEngine(
            experiment_store=self.experiments,
            apply_store=self.applies,
            signer=self.signer,
            workspace=self.workspace,
            golden_tasks_path=ROOT / "evals" / "golden_tasks.json",
            executor_factory=executor_factory,
        )

    def close(self):
        self.experiments.close(); self.applies.conn.close()


class TestApprovalGatedApply(unittest.TestCase):
    def test_valid_human_approval_applies_once_and_is_audited(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ApplyFixture(Path(temporary))
            try:
                result = fixture.engine.apply(fixture.experiment.experiment_id, fixture.approval)
                self.assertEqual(result.status, "APPLIED")
                self.assertFalse(result.rollback_verified)
                self.assertEqual(json.loads(fixture.target.read_text())["negative_yes_probability"], 0.2)
                row = fixture.applies.transaction(result.transaction_id)
                self.assertEqual(row["status"], "APPLIED")
                self.assertEqual(
                    [event["stage"] for event in fixture.applies.events(result.transaction_id)],
                    ["approval_verified", "pre_apply_snapshot_created", "declarative_apply_completed",
                     "post_apply_golden_evals", "transaction_committed"],
                )
            finally: fixture.close()

    def test_missing_forged_ai_and_wrong_intent_approvals_are_denied_before_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ApplyFixture(Path(temporary))
            try:
                with self.assertRaises(ValueError):
                    fixture.signer.issue(experiment_id="x", snapshot_digest="x", candidate_id="x",
                                         suite_digest="x", approver_id="agent", intent=APPROVAL_INTENT,
                                         signer_kind="AI")
                with self.assertRaises(ValueError):
                    fixture.signer.issue(experiment_id="x", snapshot_digest="x", candidate_id="x",
                                         suite_digest="x", approver_id="human", intent="approve")
                forged = replace(fixture.approval, signature="0" * 64)
                with self.assertRaisesRegex(ValueError, "invalid"):
                    fixture.engine.apply(fixture.experiment.experiment_id, forged)
                self.assertEqual(fixture.target.read_bytes(), fixture.original)
            finally: fixture.close()

    def test_approval_binding_and_single_use_prevent_substitution_and_replay(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ApplyFixture(Path(temporary))
            try:
                wrong = fixture.signer.issue(
                    experiment_id=fixture.experiment.experiment_id,
                    snapshot_digest="0" * 64,
                    candidate_id="candidate-sb020",
                    suite_digest=fixture.experiment.suite_digest,
                    approver_id="human:test-owner", intent=APPROVAL_INTENT,
                )
                with self.assertRaisesRegex(ValueError, "not bound"):
                    fixture.engine.apply(fixture.experiment.experiment_id, wrong)
                first = fixture.engine.apply(fixture.experiment.experiment_id, fixture.approval)
                with self.assertRaisesRegex(ValueError, "already been consumed"):
                    fixture.engine.apply(fixture.experiment.experiment_id, fixture.approval)
                self.assertEqual(first.status, "APPLIED")
            finally: fixture.close()

    def test_post_apply_regression_rolls_back_and_verifies_original_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ApplyFixture(Path(temporary), replacement_probability=0.90)
            try:
                result = fixture.engine.apply(fixture.experiment.experiment_id, fixture.approval)
                self.assertEqual(result.status, "ROLLED_BACK")
                self.assertTrue(result.rollback_verified)
                self.assertTrue(result.regressions)
                self.assertEqual(fixture.target.read_bytes(), fixture.original)
                self.assertEqual(
                    [event["stage"] for event in fixture.applies.events(result.transaction_id)][-2:],
                    ["rollback_completed", "rollback_verified"],
                )
            finally: fixture.close()

    def test_precondition_mismatch_and_executable_plan_are_denied(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ApplyFixture(Path(temporary))
            try:
                fixture.target.write_text("changed outside transaction", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "precondition hash mismatch"):
                    fixture.engine.apply(fixture.experiment.experiment_id, fixture.approval)
                self.assertEqual(fixture.applies.conn.execute("SELECT count(*) FROM approvals").fetchone()[0], 0)
            finally: fixture.close()

    def test_persisted_approval_and_terminal_transaction_are_immutable(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ApplyFixture(Path(temporary))
            try:
                result = fixture.engine.apply(fixture.experiment.experiment_id, fixture.approval)
                with self.assertRaises(Exception):
                    fixture.applies.conn.execute("DELETE FROM approvals")
                with self.assertRaises(Exception):
                    fixture.applies.conn.execute("UPDATE approvals SET signature='x'")
                with self.assertRaises(Exception):
                    fixture.applies.conn.execute(
                        "UPDATE apply_transactions SET status='FAILED' WHERE transaction_id=?",
                        (result.transaction_id,),
                    )
            finally: fixture.close()


if __name__ == "__main__": unittest.main()
