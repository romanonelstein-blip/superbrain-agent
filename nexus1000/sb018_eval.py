from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from .evals import (
    EvalExecution,
    EvalReport,
    GoldenEvalRunner,
    GoldenTask,
    NexusGoldenExecutor,
    PromotionPolicy,
    load_golden_suite,
    write_comparison_report,
)


class RegressionExampleExecutor:
    """A deterministic unsafe candidate used only to prove rejection behavior."""

    executor_id = "nexus1000-regression-example"

    def __init__(self) -> None:
        self.delegate = NexusGoldenExecutor()

    def execute(self, task: GoldenTask) -> EvalExecution:
        actual = self.delegate.execute(task)
        predicted_result = actual.predicted_result
        yes_probability = actual.yes_probability
        if task.task_id == "verified-diverse-support":
            predicted_result = "NO"
            yes_probability = 0.10
        return replace(
            actual,
            predicted_result=predicted_result,
            yes_probability=yes_probability,
            cost_units=actual.cost_units + 2.0,
            latency_ms=actual.latency_ms + 100.0,
        )


def _load_baseline(path: Path) -> EvalReport:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("golden baseline must be a JSON object")
    return EvalReport.from_dict(payload)


def run_evaluation(
    repository_root: str | Path | None = None,
    output_directory: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(repository_root or Path(__file__).resolve().parents[1])
    suite = load_golden_suite(root / "evals" / "golden_tasks.json")
    baseline = _load_baseline(root / "evals" / "golden_baseline.json")
    runner = GoldenEvalRunner(suite)
    policy = PromotionPolicy()

    current = runner.run(NexusGoldenExecutor(), run_id="sb018-current-runtime")
    current_comparison = policy.compare(
        baseline,
        current,
        "sb018-current-runtime",
        "Current canonical Nexus-1000 runtime against the accepted SB-017 baseline.",
    )

    regressed = runner.run(
        RegressionExampleExecutor(),
        run_id="sb018-regression-example",
    )
    regression_comparison = policy.compare(
        baseline,
        regressed,
        "sb018-regression-example",
        "Synthetic unsafe change that reduces correctness and increases cost and latency.",
    )

    result: dict[str, Any] = {
        "milestone": "SB-018",
        "suite_id": suite.suite_id,
        "suite_digest": suite.digest,
        "golden_task_count": len(suite.tasks),
        "current_comparison": current_comparison.to_dict(),
        "regression_example": regression_comparison.to_dict(),
        "safety": {
            "automatic_code_changes_allowed": False,
            "automatic_behavior_changes_allowed": False,
            "explicit_approval_required_for_eligible_candidate": True,
            "changes_applied": 0,
        },
    }

    if output_directory is not None:
        output = Path(output_directory)
        write_comparison_report(
            current_comparison,
            output / "sb018-current-comparison.json",
            output / "sb018-current-comparison.md",
        )
        write_comparison_report(
            regression_comparison,
            output / "sb018-regression-example.json",
            output / "sb018-regression-example.md",
        )
        summary_target = output / "sb018-eval-summary.json"
        summary_target.parent.mkdir(parents=True, exist_ok=True)
        summary_target.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    if regression_comparison.decision.status != "REJECTED_REGRESSION":
        raise RuntimeError("SB-018 regression example was not rejected")
    if regression_comparison.decision.automatic_change_applied:
        raise RuntimeError("SB-018 must never apply the regression example")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run SB-018 Golden Evals and promotion gates")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Optional directory for JSON and Markdown comparison reports",
    )
    args = parser.parse_args()
    result = run_evaluation(output_directory=args.output_dir)
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["current_comparison"]["decision"]["quality_gate_passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
