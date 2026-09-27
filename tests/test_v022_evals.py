import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from nexus1000.evals import (
    EvalExecution,
    EvalMetrics,
    EvalReport,
    GoldenEvalRunner,
    NexusGoldenExecutor,
    PromotionPolicy,
    TaskEvaluation,
    load_golden_suite,
    write_comparison_report,
)


ROOT = Path(__file__).resolve().parents[1]
GOLDEN_TASKS = ROOT / "evals" / "golden_tasks.json"


def task_score(
    task_id: str,
    *,
    correct: bool = True,
    evidence_quality: float = 0.9,
    calibration_score: float = 0.9,
    cost: float = 3.0,
    latency: float = 10.0,
) -> TaskEvaluation:
    brier_loss = 1.0 - calibration_score
    yes_probability = max(0.0, 1.0 - brier_loss ** 0.5)
    return TaskEvaluation(
        task_id=task_id,
        expected_result="YES",
        predicted_result="YES" if correct else "NO",
        correct=correct,
        yes_probability=yes_probability,
        brier_loss=brier_loss,
        evidence_quality=evidence_quality,
        verifier_passed=True,
        evidence_count=2,
        source_family_count=2,
        verified_ratio=1.0,
        provenance_ratio=1.0,
        cost_units=cost,
        latency_ms=latency,
        within_cost_budget=True,
        within_latency_budget=True,
    )


def report(
    *,
    accuracy: float = 1.0,
    evidence_quality: float = 0.9,
    calibration_score: float = 0.9,
    cost: float = 3.0,
    latency: float = 10.0,
    maximum_latency: float = 12.0,
    suite_digest: str = "digest",
) -> EvalReport:
    task_count = 5
    correct_count = round(accuracy * task_count)
    other_latency = (task_count * latency - maximum_latency) / (task_count - 1)
    tasks = tuple(
        task_score(
            f"task-{index}",
            correct=index < correct_count,
            evidence_quality=evidence_quality,
            calibration_score=calibration_score,
            cost=cost,
            latency=maximum_latency if index == 0 else other_latency,
        )
        for index in range(task_count)
    )
    return EvalReport(
        schema_version="sb018.report.v1",
        suite_id="suite",
        suite_digest=suite_digest,
        run_id="run",
        created_at="2026-09-20T00:00:00+00:00",
        executor_id="executor",
        tasks=tasks,
        metrics=EvalMetrics(
            accuracy=accuracy,
            evidence_quality=evidence_quality,
            calibration_score=calibration_score,
            mean_cost_units=cost,
            mean_latency_ms=latency,
            max_latency_ms=maximum_latency,
        ),
    )


class ScriptedExecutor:
    executor_id = "scripted"

    def execute(self, task):
        return EvalExecution(
            predicted_result=task.expected_result,
            yes_probability=0.9 if task.expected_result == "YES" else 0.1,
            verifier_passed=task.expected_verifier_passed,
            evidence=task.evidence,
            cost_units=2.0,
            latency_ms=5.0,
        )


class TestGoldenSuiteAndRunner(unittest.TestCase):
    def test_fixed_suite_loads_with_stable_digest_and_unique_tasks(self):
        first = load_golden_suite(GOLDEN_TASKS)
        second = load_golden_suite(GOLDEN_TASKS)

        self.assertEqual(first.suite_id, "nexus-safety-core-v1")
        self.assertEqual(len(first.tasks), 5)
        self.assertEqual(first.digest, second.digest)
        self.assertEqual(len(first.digest), 64)
        self.assertEqual(len({task.task_id for task in first.tasks}), 5)

    def test_accepted_baseline_is_bound_to_exact_golden_suite(self):
        suite = load_golden_suite(GOLDEN_TASKS)
        payload = json.loads((ROOT / "evals" / "golden_baseline.json").read_text(encoding="utf-8"))
        baseline = EvalReport.from_dict(payload)

        self.assertEqual(baseline.suite_id, suite.suite_id)
        self.assertEqual(baseline.suite_digest, suite.digest)
        self.assertEqual({item.task_id for item in baseline.tasks}, {task.task_id for task in suite.tasks})

    def test_relevant_change_workflow_runs_every_quality_gate(self):
        workflow = (ROOT / ".github" / "workflows" / "sb018-quality.yml").read_text(
            encoding="utf-8"
        )

        for path_filter in ("nexus1000/**", "tests/**", "evals/**", "superbrain_orchestrator_v2/**"):
            self.assertIn(path_filter, workflow)
        for command in (
            "python -m unittest discover",
            "python -m nexus1000.sb018_eval",
            "npm test",
            "npm run typecheck",
            "npm run build:bridge",
        ):
            self.assertIn(command, workflow)

    def test_runner_aggregates_all_required_metrics(self):
        suite = load_golden_suite(GOLDEN_TASKS)
        evaluated = GoldenEvalRunner(suite).run(
            ScriptedExecutor(),
            run_id="scripted-run",
            created_at="2026-09-20T00:00:00+00:00",
        )

        self.assertEqual(evaluated.metrics.accuracy, 1.0)
        self.assertEqual(evaluated.metrics.evidence_quality, 1.0)
        self.assertAlmostEqual(evaluated.metrics.calibration_score, 0.99)
        self.assertEqual(evaluated.metrics.mean_cost_units, 2.0)
        self.assertEqual(evaluated.metrics.mean_latency_ms, 5.0)
        self.assertEqual(evaluated.metrics.max_latency_ms, 5.0)
        self.assertTrue(all(item.within_cost_budget for item in evaluated.tasks))
        self.assertTrue(all(item.within_latency_budget for item in evaluated.tasks))

    def test_canonical_nexus_passes_all_golden_expected_results(self):
        suite = load_golden_suite(GOLDEN_TASKS)
        evaluated = GoldenEvalRunner(suite).run(
            NexusGoldenExecutor(),
            run_id="canonical",
            created_at="2026-09-20T00:00:00+00:00",
        )

        self.assertEqual(evaluated.metrics.accuracy, 1.0)
        self.assertEqual(evaluated.metrics.evidence_quality, 1.0)
        self.assertTrue(all(item.correct for item in evaluated.tasks))
        self.assertTrue(all(item.within_cost_budget for item in evaluated.tasks))
        self.assertTrue(all(item.within_latency_budget for item in evaluated.tasks))


class TestPromotionPolicy(unittest.TestCase):
    def setUp(self):
        self.policy = PromotionPolicy(latency_absolute_tolerance_ms=2.0, latency_relative_tolerance=0.1)

    def test_quality_improvement_without_regression_is_only_eligible_for_approval(self):
        baseline = report(evidence_quality=0.8)
        candidate = report(evidence_quality=0.9)

        decision = self.policy.evaluate(baseline, candidate, "candidate", "description")

        self.assertEqual(decision.status, "ELIGIBLE_FOR_EXPLICIT_APPROVAL")
        self.assertTrue(decision.quality_gate_passed)
        self.assertTrue(decision.promotion_eligible)
        self.assertTrue(decision.requires_explicit_approval)
        self.assertFalse(decision.automatic_change_applied)

    def test_equal_metrics_pass_gate_but_do_not_qualify_for_promotion(self):
        decision = self.policy.evaluate(report(), report(), "candidate", "description")

        self.assertEqual(decision.status, "NO_PROMOTION")
        self.assertTrue(decision.quality_gate_passed)
        self.assertFalse(decision.promotion_eligible)
        self.assertFalse(decision.automatic_change_applied)

    def test_correctness_regression_rejects_even_when_cost_improves(self):
        baseline = report()
        candidate = report(accuracy=0.8, cost=2.0)

        decision = self.policy.evaluate(baseline, candidate, "candidate", "description")

        self.assertEqual(decision.status, "REJECTED_REGRESSION")
        self.assertFalse(decision.quality_gate_passed)
        self.assertTrue(any("accuracy" in reason for reason in decision.regressions))
        self.assertTrue(any("task became incorrect" in reason for reason in decision.regressions))

    def test_evidence_quality_regression_is_rejected(self):
        decision = self.policy.evaluate(
            report(evidence_quality=0.9),
            report(evidence_quality=0.8),
            "candidate",
            "description",
        )

        self.assertEqual(decision.status, "REJECTED_REGRESSION")
        self.assertTrue(any("evidence_quality" in reason for reason in decision.regressions))

    def test_latency_regression_beyond_noise_tolerance_is_rejected(self):
        decision = self.policy.evaluate(
            report(latency=10.0, maximum_latency=12.0),
            report(latency=13.0, maximum_latency=16.0),
            "candidate",
            "description",
        )

        self.assertEqual(decision.status, "REJECTED_REGRESSION")
        self.assertTrue(any("latency" in reason for reason in decision.regressions))

    def test_suite_digest_mismatch_fails_closed(self):
        decision = self.policy.evaluate(
            report(suite_digest="baseline"),
            report(suite_digest="candidate"),
            "candidate",
            "description",
        )

        self.assertEqual(decision.status, "REJECTED_REGRESSION")
        self.assertFalse(decision.quality_gate_passed)
        self.assertTrue(any("suite digest" in reason for reason in decision.regressions))

    def test_budget_breach_is_rejected(self):
        candidate = report()
        candidate_tasks = (
            replace(candidate.tasks[0], within_cost_budget=False),
            *candidate.tasks[1:],
        )
        candidate = replace(candidate, tasks=candidate_tasks)

        decision = self.policy.evaluate(report(), candidate, "candidate", "description")

        self.assertEqual(decision.status, "REJECTED_REGRESSION")
        self.assertTrue(any("cost budget" in reason for reason in decision.regressions))

    def test_declared_metrics_that_do_not_match_tasks_are_rejected(self):
        candidate = report()
        candidate = replace(
            candidate,
            metrics=replace(candidate.metrics, accuracy=0.8),
        )

        decision = self.policy.evaluate(report(), candidate, "candidate", "description")

        self.assertEqual(decision.status, "REJECTED_REGRESSION")
        self.assertTrue(any("metric mismatch" in reason for reason in decision.regressions))

    def test_comparative_report_writes_machine_and_human_readable_artifacts(self):
        comparison = self.policy.compare(report(), report(), "candidate", "description")
        with tempfile.TemporaryDirectory() as temporary:
            json_path = Path(temporary) / "report.json"
            markdown_path = Path(temporary) / "report.md"
            write_comparison_report(comparison, json_path, markdown_path)

            payload = json.loads(json_path.read_text(encoding="utf-8"))
            markdown = markdown_path.read_text(encoding="utf-8")
            self.assertEqual(payload["decision"]["status"], "NO_PROMOTION")
            self.assertIn("Golden Eval Comparison", markdown)
            self.assertIn("NO_PROMOTION", markdown)
            self.assertIn("automatic_change_applied", markdown)


if __name__ == "__main__":
    unittest.main()
