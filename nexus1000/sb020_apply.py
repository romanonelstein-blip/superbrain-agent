from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any

from .approvals import (
    APPROVAL_INTENT,
    ApprovalGatedApplyEngine,
    HumanApprovalSigner,
    SQLiteApplyStore,
)
from .evals import NexusGoldenExecutor
from .experiments import ExperimentArtifact, ExperimentCandidate, ExperimentEngine, SQLiteExperimentStore


class _CalibrationExecutor:
    executor_id = "sb020-approved-calibration"

    def __init__(self, probability: float = 0.20) -> None:
        self.delegate = NexusGoldenExecutor()
        self.probability = probability

    def execute(self, task, sandbox=None):
        result = self.delegate.execute(task)
        if sandbox is not None:
            sandbox.read_candidate_artifact("apply-plan.json")
        probability = result.yes_probability if result.predicted_result == "YES" else self.probability
        return replace(result, yes_probability=probability)


def _executor_factory(workspace: Path) -> _CalibrationExecutor:
    policy = json.loads((workspace / "runtime-policy.json").read_text(encoding="utf-8"))
    return _CalibrationExecutor(float(policy["negative_yes_probability"]))


def run_apply(repository_root: str | Path | None = None) -> dict[str, Any]:
    root = Path(repository_root or Path(__file__).resolve().parents[1])
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        target_workspace = work / "controlled-workspace"
        target_workspace.mkdir()
        target = target_workspace / "runtime-policy.json"
        before = b'{"negative_yes_probability": 0.49}'
        target.write_bytes(before)
        replacement = json.dumps({"negative_yes_probability": 0.20}, sort_keys=True).encode()
        plan = {
            "schema_version": "sb020.apply.v1",
            "operations": [{
                "op": "replace", "path": "runtime-policy.json",
                "source_artifact": "payload/runtime-policy.json",
                "expected_before_sha256": hashlib.sha256(before).hexdigest(),
            }],
        }
        experiment_db = work / "experiments.db"
        apply_db = work / "apply.db"
        with SQLiteExperimentStore(experiment_db) as experiments:
            experiment = ExperimentEngine(
                golden_tasks_path=root / "evals" / "golden_tasks.json",
                baseline_path=root / "evals" / "golden_baseline.json",
                store=experiments, sandbox_root=work / "sandboxes",
            ).run(
                ExperimentCandidate(
                    "candidate-sb020-apply-v1", "Apply the eligible calibration policy.", "PROPOSED",
                    (ExperimentArtifact("apply-plan.json", json.dumps(plan, sort_keys=True).encode(), "application/json"),
                     ExperimentArtifact("payload/runtime-policy.json", replacement, "application/json")),
                ),
                _CalibrationExecutor(),
            )
            stored = experiments.get_experiment(experiment.experiment_id)
            signer = HumanApprovalSigner(b"sb020-local-human-acceptance-key-material")
            approval = signer.issue(
                experiment_id=stored.experiment_id, snapshot_digest=stored.snapshot_digest,
                candidate_id=stored.candidate_id, suite_digest=stored.snapshot["suite_digest"],
                approver_id="human:sb020-acceptance-owner", intent=APPROVAL_INTENT,
            )
            with SQLiteApplyStore(apply_db) as applies:
                result = ApprovalGatedApplyEngine(
                    experiment_store=experiments, apply_store=applies, signer=signer,
                    workspace=target_workspace, golden_tasks_path=root / "evals" / "golden_tasks.json",
                    executor_factory=_executor_factory,
                ).apply(stored.experiment_id, approval)
                row = applies.transaction(result.transaction_id)
                events = applies.events(result.transaction_id)
                approval_row = applies.conn.execute(
                    "SELECT * FROM approvals WHERE approval_id=?", (approval.approval_id,)
                ).fetchone()
        payload = {
            "milestone": "SB-020",
            "experiment": {"id": experiment.experiment_id, "decision": experiment.decision,
                           "snapshot_digest": experiment.snapshot_digest},
            "approval": {"id": approval.approval_id, "payload_digest": approval.payload_digest,
                         "signature_verified": signer.verify(approval), "signer_kind": approval.signer_kind,
                         "approver_id": approval.approver_id, "consumed_once": approval_row["consumed_by"] == result.transaction_id},
            "transaction": {"id": result.transaction_id, "status": row["status"],
                            "pre_apply_snapshot_digest": result.pre_apply_snapshot_digest,
                            "applied_paths": list(result.applied_paths),
                            "rollback_verified": result.rollback_verified},
            "post_apply": {"suite_digest": result.post_apply_report.suite_digest,
                           "accuracy": result.post_apply_report.metrics.accuracy,
                           "evidence_quality": result.post_apply_report.metrics.evidence_quality,
                           "calibration_score": result.post_apply_report.metrics.calibration_score},
            "target": {"before_sha256": hashlib.sha256(before).hexdigest(),
                       "after_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                       "value": json.loads(target.read_text())},
            "trace": [event["stage"] for event in events],
            "deployment_performed": False,
        }
        if (payload["experiment"]["decision"] != "ELIGIBLE_FOR_APPROVAL"
                or payload["transaction"]["status"] != "APPLIED"
                or not payload["approval"]["signature_verified"]
                or not payload["approval"]["consumed_once"]
                or payload["target"]["value"]["negative_yes_probability"] != 0.2):
            raise RuntimeError(f"SB-020 acceptance invariants failed: {payload}")
        return payload


def main() -> None:
    print(json.dumps(run_apply(), indent=2, sort_keys=True))


if __name__ == "__main__": main()
