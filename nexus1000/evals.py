from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Callable, Protocol

from .models import Evidence, FinalDecision, Stance
from .orchestrator import NexusOrchestrator


GOLDEN_SCHEMA_VERSION = "sb018.golden.v1"
REPORT_SCHEMA_VERSION = "sb018.report.v1"


def _require_probability(name: str, value: float) -> None:
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be finite and in [0, 1]")


def _canonical_digest(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class GoldenTask:
    task_id: str
    mission: str
    expected_result: str
    expected_verifier_passed: bool
    min_source_families: int
    min_verified_ratio: float
    min_provenance_ratio: float
    max_cost_units: float
    max_latency_ms: float
    evidence: tuple[Evidence, ...]

    def __post_init__(self) -> None:
        if not self.task_id.strip() or not self.mission.strip():
            raise ValueError("golden task id and mission cannot be empty")
        if self.expected_result not in {"YES", "NO"}:
            raise ValueError("golden task expected_result must be YES or NO")
        if self.min_source_families < 0:
            raise ValueError("min_source_families cannot be negative")
        _require_probability("min_verified_ratio", self.min_verified_ratio)
        _require_probability("min_provenance_ratio", self.min_provenance_ratio)
        if not math.isfinite(self.max_cost_units) or self.max_cost_units <= 0:
            raise ValueError("max_cost_units must be positive and finite")
        if not math.isfinite(self.max_latency_ms) or self.max_latency_ms <= 0:
            raise ValueError("max_latency_ms must be positive and finite")
        if not self.evidence:
            raise ValueError("golden task must contain evidence")
        evidence_ids = [item.id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError(f"duplicate evidence ids in golden task: {self.task_id}")


@dataclass(frozen=True)
class GoldenSuite:
    schema_version: str
    suite_id: str
    digest: str
    tasks: tuple[GoldenTask, ...]


@dataclass(frozen=True)
class EvalExecution:
    predicted_result: str
    yes_probability: float
    verifier_passed: bool
    evidence: tuple[Evidence, ...]
    cost_units: float
    latency_ms: float

    def __post_init__(self) -> None:
        if self.predicted_result not in {"YES", "NO"}:
            raise ValueError("predicted_result must be YES or NO")
        _require_probability("yes_probability", self.yes_probability)
        for name in ("cost_units", "latency_ms"):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")


class GoldenTaskExecutor(Protocol):
    executor_id: str

    def execute(self, task: GoldenTask) -> EvalExecution:
        ...


@dataclass(frozen=True)
class TaskEvaluation:
    task_id: str
    expected_result: str
    predicted_result: str
    correct: bool
    yes_probability: float
    brier_loss: float
    evidence_quality: float
    verifier_passed: bool
    evidence_count: int
    source_family_count: int
    verified_ratio: float
    provenance_ratio: float
    cost_units: float
    latency_ms: float
    within_cost_budget: bool
    within_latency_budget: bool


@dataclass(frozen=True)
class EvalMetrics:
    accuracy: float
    evidence_quality: float
    calibration_score: float
    mean_cost_units: float
    mean_latency_ms: float
    max_latency_ms: float

    def __post_init__(self) -> None:
        for name in ("accuracy", "evidence_quality", "calibration_score"):
            _require_probability(name, getattr(self, name))
        for name in ("mean_cost_units", "mean_latency_ms", "max_latency_ms"):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")


def _aggregate_task_metrics(tasks: tuple[TaskEvaluation, ...]) -> EvalMetrics:
    if not tasks:
        raise ValueError("evaluation report must contain task results")
    count = len(tasks)
    return EvalMetrics(
        accuracy=sum(1.0 for item in tasks if item.correct) / count,
        evidence_quality=sum(item.evidence_quality for item in tasks) / count,
        calibration_score=1.0 - sum(item.brier_loss for item in tasks) / count,
        mean_cost_units=sum(item.cost_units for item in tasks) / count,
        mean_latency_ms=sum(item.latency_ms for item in tasks) / count,
        max_latency_ms=max(item.latency_ms for item in tasks),
    )


@dataclass(frozen=True)
class EvalReport:
    schema_version: str
    suite_id: str
    suite_digest: str
    run_id: str
    created_at: str
    executor_id: str
    tasks: tuple[TaskEvaluation, ...]
    metrics: EvalMetrics

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> EvalReport:
        raw_tasks = payload.get("tasks")
        raw_metrics = payload.get("metrics")
        if not isinstance(raw_tasks, list) or not isinstance(raw_metrics, dict):
            raise ValueError("invalid evaluation report payload")
        return cls(
            schema_version=str(payload["schema_version"]),
            suite_id=str(payload["suite_id"]),
            suite_digest=str(payload["suite_digest"]),
            run_id=str(payload["run_id"]),
            created_at=str(payload["created_at"]),
            executor_id=str(payload["executor_id"]),
            tasks=tuple(TaskEvaluation(**item) for item in raw_tasks),
            metrics=EvalMetrics(**raw_metrics),
        )


@dataclass(frozen=True)
class PromotionDecision:
    candidate_id: str
    description: str
    status: str
    quality_gate_passed: bool
    promotion_eligible: bool
    requires_explicit_approval: bool
    automatic_change_applied: bool
    regressions: tuple[str, ...]
    improvements: tuple[str, ...]


@dataclass(frozen=True)
class ComparativeReport:
    schema_version: str
    baseline: EvalReport
    candidate: EvalReport
    decision: PromotionDecision

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def load_golden_suite(path: str | Path) -> GoldenSuite:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("schema_version") != GOLDEN_SCHEMA_VERSION:
        raise ValueError(f"unsupported golden schema: {raw.get('schema_version')}")
    suite_id = raw.get("suite_id")
    raw_tasks = raw.get("tasks")
    if not isinstance(suite_id, str) or not suite_id.strip():
        raise ValueError("golden suite_id cannot be empty")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise ValueError("golden suite must contain tasks")

    tasks: list[GoldenTask] = []
    for raw_task in raw_tasks:
        expectations = raw_task["evidence_expectations"]
        evidence: list[Evidence] = []
        for item in raw_task["evidence"]:
            evidence.append(Evidence(
                id=item["id"],
                claim=item["claim"],
                stance=Stance(item["stance"]),
                source_id=item["source_id"],
                source_family=item["source_family"],
                reliability=float(item["reliability"]),
                freshness=float(item["freshness"]),
                relevance=float(item["relevance"]),
                verified=bool(item["verified"]),
                citation=item.get("citation"),
                content_hash=item.get("content_hash"),
                provider="golden-fixture",
                provider_model="nexus-golden-v1",
                provider_request_id=raw_task["id"],
                provider_agent="golden-eval",
                provider_attempts=int(item.get("provider_attempts", 1)),
                provider_latency_ms=0,
            ))
        tasks.append(GoldenTask(
            task_id=raw_task["id"],
            mission=raw_task["mission"],
            expected_result=raw_task["expected_result"],
            expected_verifier_passed=bool(expectations["verifier_passed"]),
            min_source_families=int(expectations["min_source_families"]),
            min_verified_ratio=float(expectations["min_verified_ratio"]),
            min_provenance_ratio=float(expectations["min_provenance_ratio"]),
            max_cost_units=float(raw_task["max_cost_units"]),
            max_latency_ms=float(raw_task["max_latency_ms"]),
            evidence=tuple(evidence),
        ))

    task_ids = [task.task_id for task in tasks]
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("golden task ids must be unique")
    return GoldenSuite(GOLDEN_SCHEMA_VERSION, suite_id, _canonical_digest(raw), tuple(tasks))


class NexusGoldenExecutor:
    executor_id = "nexus1000-canonical"

    def __init__(self, timer: Callable[[], float] | None = None) -> None:
        self.timer = timer or (lambda: perf_counter() * 1_000.0)

    @staticmethod
    def _yes_probability(final: FinalDecision) -> float:
        metrics = final.grand_council.metrics
        total_strength = metrics.support_strength + metrics.challenge_strength
        support_ratio = metrics.support_strength / total_strength if total_strength else 0.5
        evidence_quality = (
            metrics.independence
            + metrics.family_diversity
            + metrics.freshness
            + metrics.reliability
        ) / 4.0
        probability = 0.60 * support_ratio + 0.40 * evidence_quality
        if final.value == "YES":
            probability = max(0.51, probability)
        else:
            probability = min(0.49, probability)
        return min(1.0, max(0.0, probability))

    @staticmethod
    def _cost_units(final: FinalDecision) -> float:
        evidence = final.grand_council.evidence
        source_families = len({item.source_family for item in evidence})
        provider_attempts = max((item.provider_attempts or 1 for item in evidence), default=1)
        return (
            1.0
            + 0.5 * len(evidence)
            + 0.25 * source_families
            + 0.5 * provider_attempts
            + float(final.grand_council.escalation_rounds)
        )

    def execute(self, task: GoldenTask) -> EvalExecution:
        started = self.timer()
        final = NexusOrchestrator().run_evidence_mission(
            task.mission,
            task.evidence,
            dissent_fn=lambda _question, _evidence: (),
            run_id=f"golden:{task.task_id}",
        )
        elapsed = max(0.0, self.timer() - started)
        return EvalExecution(
            predicted_result=final.value,
            yes_probability=self._yes_probability(final),
            verifier_passed=final.pipeline_passes["verifier"],
            evidence=final.grand_council.evidence,
            cost_units=self._cost_units(final),
            latency_ms=elapsed,
        )


class GoldenEvalRunner:
    def __init__(self, suite: GoldenSuite) -> None:
        self.suite = suite

    @staticmethod
    def _task_evaluation(task: GoldenTask, execution: EvalExecution) -> TaskEvaluation:
        evidence_count = len(execution.evidence)
        source_family_count = len({item.source_family for item in execution.evidence})
        verified_ratio = (
            sum(1 for item in execution.evidence if item.verified) / evidence_count
            if evidence_count
            else 0.0
        )
        provenance_ratio = (
            sum(
                1
                for item in execution.evidence
                if item.citation and item.content_hash and item.source_id and item.source_family
            ) / evidence_count
            if evidence_count
            else 0.0
        )
        evidence_checks = (
            execution.verifier_passed == task.expected_verifier_passed,
            source_family_count >= task.min_source_families,
            verified_ratio >= task.min_verified_ratio,
            provenance_ratio >= task.min_provenance_ratio,
        )
        evidence_quality = sum(1.0 for passed in evidence_checks if passed) / len(evidence_checks)
        expected_yes = 1.0 if task.expected_result == "YES" else 0.0
        brier_loss = (execution.yes_probability - expected_yes) ** 2
        return TaskEvaluation(
            task_id=task.task_id,
            expected_result=task.expected_result,
            predicted_result=execution.predicted_result,
            correct=execution.predicted_result == task.expected_result,
            yes_probability=execution.yes_probability,
            brier_loss=brier_loss,
            evidence_quality=evidence_quality,
            verifier_passed=execution.verifier_passed,
            evidence_count=evidence_count,
            source_family_count=source_family_count,
            verified_ratio=verified_ratio,
            provenance_ratio=provenance_ratio,
            cost_units=execution.cost_units,
            latency_ms=execution.latency_ms,
            within_cost_budget=execution.cost_units <= task.max_cost_units,
            within_latency_budget=execution.latency_ms <= task.max_latency_ms,
        )

    def run(
        self,
        executor: GoldenTaskExecutor,
        *,
        run_id: str,
        created_at: str | None = None,
    ) -> EvalReport:
        evaluated = tuple(
            self._task_evaluation(task, executor.execute(task)) for task in self.suite.tasks
        )
        metrics = _aggregate_task_metrics(evaluated)
        return EvalReport(
            schema_version=REPORT_SCHEMA_VERSION,
            suite_id=self.suite.suite_id,
            suite_digest=self.suite.digest,
            run_id=run_id,
            created_at=created_at or datetime.now(timezone.utc).isoformat(),
            executor_id=executor.executor_id,
            tasks=evaluated,
            metrics=metrics,
        )


class PromotionPolicy:
    def __init__(
        self,
        *,
        metric_epsilon: float = 1e-9,
        min_primary_improvement: float = 0.001,
        latency_absolute_tolerance_ms: float = 25.0,
        latency_relative_tolerance: float = 0.20,
    ) -> None:
        if metric_epsilon < 0 or min_primary_improvement <= 0:
            raise ValueError("metric thresholds must be positive")
        if latency_absolute_tolerance_ms < 0 or latency_relative_tolerance < 0:
            raise ValueError("latency tolerances cannot be negative")
        self.metric_epsilon = metric_epsilon
        self.min_primary_improvement = min_primary_improvement
        self.latency_absolute_tolerance_ms = latency_absolute_tolerance_ms
        self.latency_relative_tolerance = latency_relative_tolerance

    def evaluate(
        self,
        baseline: EvalReport,
        candidate: EvalReport,
        candidate_id: str,
        description: str,
    ) -> PromotionDecision:
        regressions: list[str] = []
        improvements: list[str] = []
        for report_name, report in (("baseline", baseline), ("candidate", candidate)):
            task_ids = [item.task_id for item in report.tasks]
            if len(task_ids) != len(set(task_ids)):
                regressions.append(f"{report_name} report contains duplicate task ids")
            try:
                calculated = _aggregate_task_metrics(report.tasks)
            except ValueError as exc:
                regressions.append(f"{report_name} report is invalid: {exc}")
            else:
                for metric_name in (
                    "accuracy",
                    "evidence_quality",
                    "calibration_score",
                    "mean_cost_units",
                    "mean_latency_ms",
                    "max_latency_ms",
                ):
                    declared = getattr(report.metrics, metric_name)
                    actual = getattr(calculated, metric_name)
                    if abs(declared - actual) > 1e-6:
                        regressions.append(
                            f"{report_name} report metric mismatch for {metric_name}: "
                            f"declared={declared:.6f}, calculated={actual:.6f}"
                        )
        if baseline.schema_version != REPORT_SCHEMA_VERSION or candidate.schema_version != REPORT_SCHEMA_VERSION:
            regressions.append("report schema mismatch")
        if baseline.suite_id != candidate.suite_id:
            regressions.append("suite id mismatch")
        if baseline.suite_digest != candidate.suite_digest:
            regressions.append("suite digest mismatch; comparisons require identical Golden Tasks")

        baseline_tasks = {item.task_id: item for item in baseline.tasks}
        candidate_tasks = {item.task_id: item for item in candidate.tasks}
        if set(baseline_tasks) != set(candidate_tasks):
            regressions.append("candidate task set differs from baseline")
        for task_id in sorted(set(baseline_tasks) & set(candidate_tasks)):
            before = baseline_tasks[task_id]
            after = candidate_tasks[task_id]
            if before.correct and not after.correct:
                regressions.append(f"task became incorrect: {task_id}")
            if not after.within_cost_budget:
                regressions.append(f"task exceeded cost budget: {task_id}")
            if not after.within_latency_budget:
                regressions.append(f"task exceeded latency budget: {task_id}")

        higher_is_better = (
            ("accuracy", baseline.metrics.accuracy, candidate.metrics.accuracy),
            (
                "evidence_quality",
                baseline.metrics.evidence_quality,
                candidate.metrics.evidence_quality,
            ),
            (
                "calibration_score",
                baseline.metrics.calibration_score,
                candidate.metrics.calibration_score,
            ),
        )
        primary_improvement = False
        for name, before, after in higher_is_better:
            if after < before - self.metric_epsilon:
                regressions.append(f"{name} regressed: {before:.6f} -> {after:.6f}")
            if after >= before + self.min_primary_improvement:
                improvements.append(f"{name} improved: {before:.6f} -> {after:.6f}")
                primary_improvement = True

        if candidate.metrics.mean_cost_units > baseline.metrics.mean_cost_units + self.metric_epsilon:
            regressions.append(
                "mean_cost_units regressed: "
                f"{baseline.metrics.mean_cost_units:.6f} -> {candidate.metrics.mean_cost_units:.6f}"
            )
        elif candidate.metrics.mean_cost_units < baseline.metrics.mean_cost_units - self.metric_epsilon:
            improvements.append(
                "mean_cost_units improved: "
                f"{baseline.metrics.mean_cost_units:.6f} -> {candidate.metrics.mean_cost_units:.6f}"
            )

        latency_tolerance = max(
            self.latency_absolute_tolerance_ms,
            baseline.metrics.mean_latency_ms * self.latency_relative_tolerance,
        )
        if candidate.metrics.mean_latency_ms > baseline.metrics.mean_latency_ms + latency_tolerance:
            regressions.append(
                "mean_latency_ms regressed beyond noise tolerance: "
                f"{baseline.metrics.mean_latency_ms:.6f} -> {candidate.metrics.mean_latency_ms:.6f}"
            )
        elif candidate.metrics.mean_latency_ms < baseline.metrics.mean_latency_ms - latency_tolerance:
            improvements.append(
                "mean_latency_ms improved beyond noise tolerance: "
                f"{baseline.metrics.mean_latency_ms:.6f} -> {candidate.metrics.mean_latency_ms:.6f}"
            )

        max_latency_tolerance = max(
            self.latency_absolute_tolerance_ms,
            baseline.metrics.max_latency_ms * self.latency_relative_tolerance,
        )
        if candidate.metrics.max_latency_ms > baseline.metrics.max_latency_ms + max_latency_tolerance:
            regressions.append(
                "max_latency_ms regressed beyond noise tolerance: "
                f"{baseline.metrics.max_latency_ms:.6f} -> {candidate.metrics.max_latency_ms:.6f}"
            )

        if regressions:
            status = "REJECTED_REGRESSION"
            quality_gate_passed = False
            promotion_eligible = False
        elif primary_improvement:
            status = "ELIGIBLE_FOR_EXPLICIT_APPROVAL"
            quality_gate_passed = True
            promotion_eligible = True
        else:
            status = "NO_PROMOTION"
            quality_gate_passed = True
            promotion_eligible = False
            improvements.append("no primary quality metric improved by the required minimum")

        return PromotionDecision(
            candidate_id=candidate_id,
            description=description,
            status=status,
            quality_gate_passed=quality_gate_passed,
            promotion_eligible=promotion_eligible,
            requires_explicit_approval=promotion_eligible,
            automatic_change_applied=False,
            regressions=tuple(regressions),
            improvements=tuple(improvements),
        )

    def compare(
        self,
        baseline: EvalReport,
        candidate: EvalReport,
        candidate_id: str,
        description: str,
    ) -> ComparativeReport:
        return ComparativeReport(
            schema_version="sb018.comparison.v1",
            baseline=baseline,
            candidate=candidate,
            decision=self.evaluate(baseline, candidate, candidate_id, description),
        )


def _comparison_markdown(report: ComparativeReport) -> str:
    before = report.baseline.metrics
    after = report.candidate.metrics
    rows = (
        ("Accuracy", before.accuracy, after.accuracy, "higher"),
        ("Evidence quality", before.evidence_quality, after.evidence_quality, "higher"),
        ("Calibration score", before.calibration_score, after.calibration_score, "higher"),
        ("Mean cost units", before.mean_cost_units, after.mean_cost_units, "lower"),
        ("Mean latency ms", before.mean_latency_ms, after.mean_latency_ms, "lower"),
        ("Max latency ms", before.max_latency_ms, after.max_latency_ms, "lower"),
    )
    lines = [
        "# Golden Eval Comparison",
        "",
        f"- Candidate: `{report.decision.candidate_id}`",
        f"- Decision: **{report.decision.status}**",
        f"- Quality gate passed: `{str(report.decision.quality_gate_passed).lower()}`",
        f"- Promotion eligible: `{str(report.decision.promotion_eligible).lower()}`",
        f"- Explicit approval required: `{str(report.decision.requires_explicit_approval).lower()}`",
        f"- automatic_change_applied: `{str(report.decision.automatic_change_applied).lower()}`",
        "",
        "| Metric | Before | After | Direction |",
        "|---|---:|---:|---|",
    ]
    lines.extend(
        f"| {name} | {baseline:.6f} | {candidate:.6f} | {direction} is better |"
        for name, baseline, candidate, direction in rows
    )
    lines.extend(["", "## Regressions", ""])
    lines.extend(f"- {item}" for item in report.decision.regressions or ("None",))
    lines.extend(["", "## Improvements", ""])
    lines.extend(f"- {item}" for item in report.decision.improvements or ("None",))
    lines.extend(["", "No code, policy, prompt, routing, or behavior change was applied.", ""])
    return "\n".join(lines)


def write_comparison_report(
    report: ComparativeReport,
    json_path: str | Path,
    markdown_path: str | Path,
) -> None:
    json_target = Path(json_path)
    markdown_target = Path(markdown_path)
    json_target.parent.mkdir(parents=True, exist_ok=True)
    markdown_target.parent.mkdir(parents=True, exist_ok=True)
    json_target.write_text(
        json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_target.write_text(_comparison_markdown(report), encoding="utf-8")
