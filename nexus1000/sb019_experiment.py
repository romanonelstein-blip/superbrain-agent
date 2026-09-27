from __future__ import annotations

import json
import tempfile
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from .evals import NexusGoldenExecutor
from .experiments import (
    ExperimentArtifact,
    ExperimentCandidate,
    ExperimentEngine,
    SQLiteExperimentStore,
)
from .learning import ImprovementCandidate


class CalibrationCandidateExecutor:
    executor_id = "sb019-calibration-candidate"

    def __init__(self) -> None:
        self.delegate = NexusGoldenExecutor()

    def execute(self, task, sandbox):
        baseline_behavior = self.delegate.execute(task)
        calibrated_probability = (
            baseline_behavior.yes_probability
            if baseline_behavior.predicted_result == "YES"
            else 0.20
        )
        sandbox.write_output_artifact(
            f"task-results/{task.task_id}.json",
            json.dumps(
                {
                    "task_id": task.task_id,
                    "predicted_result": baseline_behavior.predicted_result,
                    "before_yes_probability": baseline_behavior.yes_probability,
                    "candidate_yes_probability": calibrated_probability,
                },
                sort_keys=True,
            ).encode("utf-8"),
            "application/json",
        )
        return replace(baseline_behavior, yes_probability=calibrated_probability)


def run_experiment(repository_root: str | Path | None = None) -> dict[str, Any]:
    root = Path(repository_root or Path(__file__).resolve().parents[1])
    source_improvement = ImprovementCandidate(
        candidate_id="candidate-sb019-calibration-v1",
        lesson_id="lesson-sb017-evidence-quality",
        description=(
            "Calibrate negative-decision confidence without changing final decisions, "
            "evidence gates, cost accounting, or canonical orchestration."
        ),
        confidence=0.90,
        status="PROPOSED",
        occurrences=1,
        first_proposed_at="2026-09-20T00:00:00+00:00",
        last_proposed_at="2026-09-20T00:00:00+00:00",
        latest_run_id="sb017-e2e",
    )
    candidate_manifest = {
        "candidate_id": source_improvement.candidate_id,
        "lesson_id": source_improvement.lesson_id,
        "description": source_improvement.description,
        "confidence": source_improvement.confidence,
        "status": source_improvement.status,
        "scope": "experiment-only calibration output",
        "applies_changes": False,
    }
    experiment_candidate = ExperimentCandidate.from_improvement_candidate(
        source_improvement,
        (
            ExperimentArtifact(
                "candidate.json",
                json.dumps(candidate_manifest, sort_keys=True).encode("utf-8"),
                "application/json",
            ),
        ),
    )

    with tempfile.TemporaryDirectory() as temporary:
        workspace = Path(temporary)
        database = workspace / "sb019-experiments.db"
        with SQLiteExperimentStore(database) as store:
            result = ExperimentEngine(
                golden_tasks_path=root / "evals" / "golden_tasks.json",
                baseline_path=root / "evals" / "golden_baseline.json",
                store=store,
                sandbox_root=workspace / "sandboxes",
            ).run(experiment_candidate, CalibrationCandidateExecutor())

        with SQLiteExperimentStore(database) as store:
            persisted = store.get_experiment(result.experiment_id)
            artifacts = store.list_artifacts(result.experiment_id)
            events = store.list_events(result.experiment_id)

        payload = {
            "milestone": "SB-019",
            "candidate": {
                "id": source_improvement.candidate_id,
                "source_lesson_id": source_improvement.lesson_id,
                "source_status": source_improvement.status,
                "source_confidence": source_improvement.confidence,
                "description": source_improvement.description,
            },
            "snapshot": {
                "experiment_id": result.experiment_id,
                "digest": result.snapshot_digest,
                "suite_digest": result.suite_digest,
                "candidate_fingerprint": persisted.snapshot["candidate_fingerprint"],
                "contract_digest": persisted.snapshot["contract_digest"],
            },
            "metrics": {
                "baseline": asdict(result.baseline_metrics),
                "candidate": asdict(result.candidate_metrics),
                "improvements": list(result.improvements),
                "regressions": list(result.regressions),
            },
            "decision": result.decision,
            "promotion_status": result.promotion_status,
            "requires_explicit_approval": result.requires_explicit_approval,
            "automatic_change_applied": result.automatic_change_applied,
            "changes_applied": 0,
            "persistence": {
                "status": persisted.status,
                "decision": persisted.decision,
                "artifact_count": len(artifacts),
                "artifact_roles": sorted({artifact.role for artifact in artifacts}),
                "artifact_hashes": [artifact.sha256 for artifact in artifacts],
                "event_count": len(events),
            },
            "timestamps": {
                "created_at": persisted.created_at,
                "started_at": persisted.started_at,
                "completed_at": persisted.completed_at,
            },
            "trace": [event.stage for event in events],
        }
        if (
            result.decision != "ELIGIBLE_FOR_APPROVAL"
            or not result.requires_explicit_approval
            or result.automatic_change_applied
            or persisted.status != "COMPLETED"
            or persisted.automatic_change_applied
            or len(artifacts) != 10
            or len(events) != 9
        ):
            raise RuntimeError(f"SB-019 acceptance invariants failed: {payload}")
        return payload


def main() -> None:
    print(json.dumps(run_experiment(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
