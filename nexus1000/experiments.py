from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable, Protocol
from uuid import uuid4

from .evals import (
    EvalExecution,
    EvalMetrics,
    EvalReport,
    GoldenEvalRunner,
    GoldenTask,
    PromotionPolicy,
    load_golden_suite,
)
from .learning import ImprovementCandidate


MAX_ARTIFACT_COUNT = 50
MAX_ARTIFACT_BYTES = 1_000_000
MAX_TOTAL_ARTIFACT_BYTES = 10_000_000


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical_json(payload: object) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _safe_relative_path(value: str) -> str:
    if not value or "\\" in value:
        raise ValueError("artifact path must be a non-empty POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"unsafe artifact path: {value}")
    return path.as_posix()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ExperimentArtifact:
    relative_path: str
    content: bytes
    media_type: str = "application/octet-stream"

    def __post_init__(self) -> None:
        object.__setattr__(self, "relative_path", _safe_relative_path(self.relative_path))
        if not isinstance(self.content, bytes):
            raise TypeError("experiment artifact content must be bytes")
        if len(self.content) > MAX_ARTIFACT_BYTES:
            raise ValueError("experiment artifact exceeds the per-file size limit")
        if not self.media_type.strip() or len(self.media_type) > 200:
            raise ValueError("artifact media_type is invalid")


@dataclass(frozen=True)
class ExperimentCandidate:
    candidate_id: str
    description: str
    status: str
    artifacts: tuple[ExperimentArtifact, ...]
    source_lesson_id: str | None = None
    source_confidence: float | None = None

    def __post_init__(self) -> None:
        if not self.candidate_id.strip() or len(self.candidate_id) > 200:
            raise ValueError("candidate_id must contain 1 to 200 characters")
        if not self.description.strip() or len(self.description) > 2_000:
            raise ValueError("candidate description must contain 1 to 2000 characters")
        if not self.artifacts or len(self.artifacts) > MAX_ARTIFACT_COUNT:
            raise ValueError(f"candidate must contain 1 to {MAX_ARTIFACT_COUNT} artifacts")
        paths = [item.relative_path for item in self.artifacts]
        if len(paths) != len(set(paths)):
            raise ValueError("candidate artifact paths must be unique")
        if sum(len(item.content) for item in self.artifacts) > MAX_TOTAL_ARTIFACT_BYTES:
            raise ValueError("candidate artifacts exceed the total size limit")
        if self.source_confidence is not None:
            if not math.isfinite(self.source_confidence) or not 0.0 <= self.source_confidence <= 1.0:
                raise ValueError("source_confidence must be finite and in [0, 1]")

    @classmethod
    def from_improvement_candidate(
        cls,
        improvement: ImprovementCandidate,
        artifacts: tuple[ExperimentArtifact, ...],
    ) -> ExperimentCandidate:
        return cls(
            candidate_id=improvement.candidate_id,
            description=improvement.description,
            status=improvement.status,
            artifacts=artifacts,
            source_lesson_id=improvement.lesson_id,
            source_confidence=improvement.confidence,
        )


@dataclass(frozen=True)
class SnapshotArtifact:
    role: str
    relative_path: str
    sha256: str
    size_bytes: int
    media_type: str


@dataclass(frozen=True)
class ExperimentSnapshot:
    experiment_id: str
    candidate_id: str
    candidate_description: str
    source_lesson_id: str | None
    source_confidence: float | None
    candidate_fingerprint: str
    executor_id: str
    suite_id: str
    suite_digest: str
    baseline_digest: str
    policy_digest: str
    contract_digest: str
    snapshot_digest: str
    created_at: str
    artifacts: tuple[SnapshotArtifact, ...]


@dataclass(frozen=True)
class ExperimentEvent:
    sequence: int
    stage: str
    detail: str
    occurred_at: str


@dataclass(frozen=True)
class StoredArtifact:
    role: str
    relative_path: str
    sha256: str
    media_type: str
    content: bytes
    created_at: str


@dataclass(frozen=True)
class StoredExperiment:
    experiment_id: str
    candidate_id: str
    status: str
    decision: str | None
    snapshot_digest: str
    snapshot: dict[str, object]
    baseline_report: EvalReport | None
    candidate_report: EvalReport | None
    comparison: dict[str, object] | None
    created_at: str
    started_at: str | None
    completed_at: str | None
    automatic_change_applied: bool
    error: str | None


@dataclass(frozen=True)
class ExperimentResult:
    experiment_id: str
    candidate_id: str
    decision: str
    promotion_status: str
    snapshot_digest: str
    suite_digest: str
    baseline_metrics: EvalMetrics
    candidate_metrics: EvalMetrics
    regressions: tuple[str, ...]
    improvements: tuple[str, ...]
    requires_explicit_approval: bool
    automatic_change_applied: bool
    trace: tuple[ExperimentEvent, ...]
    artifact_hashes: tuple[str, ...]


class CandidateExperimentExecutor(Protocol):
    executor_id: str

    def execute(self, task: GoldenTask, sandbox: ExperimentSandbox) -> EvalExecution:
        ...


class ExperimentSandbox:
    """Bounded candidate artifact API backed by a disposable private directory."""

    def __init__(self, root: Path, artifacts: tuple[ExperimentArtifact, ...]) -> None:
        self._root = root
        self._input_root = root / "input"
        self._output_root = root / "output"
        self._inputs = {item.relative_path: item for item in artifacts}
        self._outputs: dict[str, ExperimentArtifact] = {}
        self._input_root.mkdir(parents=True, exist_ok=False)
        self._output_root.mkdir(parents=True, exist_ok=False)
        for artifact in artifacts:
            target = self._input_root.joinpath(*PurePosixPath(artifact.relative_path).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(artifact.content)
            os.chmod(target, 0o444)

    def read_candidate_artifact(self, relative_path: str) -> bytes:
        safe_path = _safe_relative_path(relative_path)
        try:
            return self._inputs[safe_path].content
        except KeyError as exc:
            raise KeyError(f"unknown candidate artifact: {safe_path}") from exc

    def write_output_artifact(
        self,
        relative_path: str,
        content: bytes,
        media_type: str = "application/octet-stream",
    ) -> None:
        artifact = ExperimentArtifact(relative_path, content, media_type)
        if artifact.relative_path in self._outputs:
            raise ValueError(f"output artifact already exists: {artifact.relative_path}")
        if len(self._outputs) >= MAX_ARTIFACT_COUNT:
            raise ValueError("sandbox output artifact count limit exceeded")
        total_size = sum(len(item.content) for item in self._outputs.values()) + len(content)
        if total_size > MAX_TOTAL_ARTIFACT_BYTES:
            raise ValueError("sandbox output artifacts exceed the total size limit")
        target = self._output_root.joinpath(*PurePosixPath(artifact.relative_path).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        self._outputs[artifact.relative_path] = artifact

    def output_artifacts(self) -> tuple[ExperimentArtifact, ...]:
        return tuple(self._outputs[path] for path in sorted(self._outputs))


class SQLiteExperimentStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._initialize()

    def _initialize(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS experiments (
                experiment_id TEXT PRIMARY KEY,
                candidate_id TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('SNAPSHOT', 'RUNNING', 'COMPLETED', 'FAILED')),
                decision TEXT CHECK(decision IN ('REJECT', 'NO_IMPROVEMENT', 'ELIGIBLE_FOR_APPROVAL')),
                snapshot_digest TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                baseline_report_json TEXT,
                candidate_report_json TEXT,
                comparison_json TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                automatic_change_applied INTEGER NOT NULL DEFAULT 0
                    CHECK(automatic_change_applied = 0),
                error TEXT
            );

            CREATE TABLE IF NOT EXISTS experiment_artifacts (
                experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id),
                role TEXT NOT NULL CHECK(role IN ('CANDIDATE', 'CONTRACT', 'OUTPUT', 'REPORT')),
                relative_path TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                media_type TEXT NOT NULL,
                content BLOB NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (experiment_id, role, relative_path)
            );

            CREATE TABLE IF NOT EXISTS experiment_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id),
                stage TEXT NOT NULL,
                detail TEXT NOT NULL,
                occurred_at TEXT NOT NULL
            );

            CREATE TRIGGER IF NOT EXISTS experiments_no_delete
            BEFORE DELETE ON experiments
            BEGIN
                SELECT RAISE(ABORT, 'experiment records are append-only');
            END;

            CREATE TRIGGER IF NOT EXISTS experiments_snapshot_immutable
            BEFORE UPDATE OF experiment_id, candidate_id, snapshot_digest, snapshot_json,
                created_at, automatic_change_applied ON experiments
            BEGIN
                SELECT RAISE(ABORT, 'experiment snapshot is immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS experiments_terminal_immutable
            BEFORE UPDATE ON experiments
            WHEN OLD.status IN ('COMPLETED', 'FAILED')
            BEGIN
                SELECT RAISE(ABORT, 'terminal experiment is immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS experiment_artifacts_no_update
            BEFORE UPDATE ON experiment_artifacts
            BEGIN
                SELECT RAISE(ABORT, 'experiment artifacts are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS experiment_artifacts_no_delete
            BEFORE DELETE ON experiment_artifacts
            BEGIN
                SELECT RAISE(ABORT, 'experiment artifacts are append-only');
            END;

            CREATE TRIGGER IF NOT EXISTS experiment_artifacts_terminal_insert
            BEFORE INSERT ON experiment_artifacts
            WHEN (SELECT status FROM experiments WHERE experiment_id = NEW.experiment_id)
                IN ('COMPLETED', 'FAILED')
            BEGIN
                SELECT RAISE(ABORT, 'terminal experiment cannot receive artifacts');
            END;

            CREATE TRIGGER IF NOT EXISTS experiment_events_no_update
            BEFORE UPDATE ON experiment_events
            BEGIN
                SELECT RAISE(ABORT, 'experiment events are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS experiment_events_no_delete
            BEFORE DELETE ON experiment_events
            BEGIN
                SELECT RAISE(ABORT, 'experiment events are append-only');
            END;

            CREATE TRIGGER IF NOT EXISTS experiment_events_terminal_insert
            BEFORE INSERT ON experiment_events
            WHEN (SELECT status FROM experiments WHERE experiment_id = NEW.experiment_id)
                IN ('COMPLETED', 'FAILED')
            BEGIN
                SELECT RAISE(ABORT, 'terminal experiment cannot receive events');
            END;
            """
        )
        self.conn.commit()

    def create(self, snapshot: ExperimentSnapshot) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO experiments (
                    experiment_id, candidate_id, status, snapshot_digest,
                    snapshot_json, created_at, automatic_change_applied
                ) VALUES (?, ?, 'SNAPSHOT', ?, ?, ?, 0)
                """,
                (
                    snapshot.experiment_id,
                    snapshot.candidate_id,
                    snapshot.snapshot_digest,
                    json.dumps(asdict(snapshot), sort_keys=True, separators=(",", ":")),
                    snapshot.created_at,
                ),
            )

    def add_artifact(
        self,
        experiment_id: str,
        role: str,
        artifact: ExperimentArtifact,
        created_at: str,
    ) -> None:
        if role not in {"CANDIDATE", "CONTRACT", "OUTPUT", "REPORT"}:
            raise ValueError(f"unsupported experiment artifact role: {role}")
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO experiment_artifacts (
                    experiment_id, role, relative_path, sha256,
                    media_type, content, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    experiment_id,
                    role,
                    artifact.relative_path,
                    _sha256(artifact.content),
                    artifact.media_type,
                    artifact.content,
                    created_at,
                ),
            )

    def add_event(self, experiment_id: str, stage: str, detail: str, occurred_at: str) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO experiment_events (experiment_id, stage, detail, occurred_at)
                VALUES (?, ?, ?, ?)
                """,
                (experiment_id, stage, detail, occurred_at),
            )

    def start(self, experiment_id: str, started_at: str) -> None:
        with self.conn:
            cursor = self.conn.execute(
                """
                UPDATE experiments SET status = 'RUNNING', started_at = ?
                WHERE experiment_id = ? AND status = 'SNAPSHOT'
                """,
                (started_at, experiment_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("experiment could not transition to RUNNING")

    def complete(
        self,
        experiment_id: str,
        decision: str,
        baseline: EvalReport,
        candidate: EvalReport,
        comparison: dict[str, object],
        completed_at: str,
    ) -> None:
        with self.conn:
            cursor = self.conn.execute(
                """
                UPDATE experiments
                SET status = 'COMPLETED', decision = ?, baseline_report_json = ?,
                    candidate_report_json = ?, comparison_json = ?, completed_at = ?
                WHERE experiment_id = ? AND status = 'RUNNING'
                """,
                (
                    decision,
                    json.dumps(baseline.to_dict(), sort_keys=True, separators=(",", ":")),
                    json.dumps(candidate.to_dict(), sort_keys=True, separators=(",", ":")),
                    json.dumps(comparison, sort_keys=True, separators=(",", ":")),
                    completed_at,
                    experiment_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("experiment could not transition to COMPLETED")

    def fail(self, experiment_id: str, error: str, completed_at: str) -> None:
        with self.conn:
            cursor = self.conn.execute(
                """
                UPDATE experiments
                SET status = 'FAILED', error = ?, completed_at = ?
                WHERE experiment_id = ? AND status IN ('SNAPSHOT', 'RUNNING')
                """,
                (error[:4_000], completed_at, experiment_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("experiment could not transition to FAILED")

    @staticmethod
    def _experiment_from_row(row: sqlite3.Row) -> StoredExperiment:
        baseline_payload = json.loads(row["baseline_report_json"]) if row["baseline_report_json"] else None
        candidate_payload = json.loads(row["candidate_report_json"]) if row["candidate_report_json"] else None
        return StoredExperiment(
            experiment_id=row["experiment_id"],
            candidate_id=row["candidate_id"],
            status=row["status"],
            decision=row["decision"],
            snapshot_digest=row["snapshot_digest"],
            snapshot=json.loads(row["snapshot_json"]),
            baseline_report=EvalReport.from_dict(baseline_payload) if baseline_payload else None,
            candidate_report=EvalReport.from_dict(candidate_payload) if candidate_payload else None,
            comparison=json.loads(row["comparison_json"]) if row["comparison_json"] else None,
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            automatic_change_applied=bool(row["automatic_change_applied"]),
            error=row["error"],
        )

    def get_experiment(self, experiment_id: str) -> StoredExperiment:
        row = self.conn.execute(
            "SELECT * FROM experiments WHERE experiment_id = ?", (experiment_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown experiment: {experiment_id}")
        return self._experiment_from_row(row)

    def list_experiments(self) -> tuple[StoredExperiment, ...]:
        rows = self.conn.execute("SELECT * FROM experiments ORDER BY created_at, experiment_id").fetchall()
        return tuple(self._experiment_from_row(row) for row in rows)

    def list_artifacts(self, experiment_id: str) -> tuple[StoredArtifact, ...]:
        rows = self.conn.execute(
            """
            SELECT role, relative_path, sha256, media_type, content, created_at
            FROM experiment_artifacts
            WHERE experiment_id = ?
            ORDER BY role, relative_path
            """,
            (experiment_id,),
        ).fetchall()
        return tuple(
            StoredArtifact(
                row["role"],
                row["relative_path"],
                row["sha256"],
                row["media_type"],
                bytes(row["content"]),
                row["created_at"],
            )
            for row in rows
        )

    def list_events(self, experiment_id: str) -> tuple[ExperimentEvent, ...]:
        rows = self.conn.execute(
            """
            SELECT sequence, stage, detail, occurred_at
            FROM experiment_events
            WHERE experiment_id = ?
            ORDER BY sequence
            """,
            (experiment_id,),
        ).fetchall()
        return tuple(
            ExperimentEvent(row["sequence"], row["stage"], row["detail"], row["occurred_at"])
            for row in rows
        )

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> SQLiteExperimentStore:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()


class _SandboxedExecutorAdapter:
    def __init__(self, executor: CandidateExperimentExecutor, sandbox: ExperimentSandbox) -> None:
        self.executor_id = executor.executor_id
        self.executor = executor
        self.sandbox = sandbox

    def execute(self, task: GoldenTask) -> EvalExecution:
        return self.executor.execute(task, self.sandbox)


class ExperimentEngine:
    def __init__(
        self,
        *,
        golden_tasks_path: str | Path,
        baseline_path: str | Path,
        store: SQLiteExperimentStore,
        sandbox_root: str | Path,
        policy: PromotionPolicy | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.golden_tasks_path = Path(golden_tasks_path)
        self.baseline_path = Path(baseline_path)
        self.store = store
        self.sandbox_root = Path(sandbox_root)
        self.sandbox_root.mkdir(parents=True, exist_ok=True)
        self.policy = policy or PromotionPolicy()
        self.clock = clock or _utc_now

    def _timestamp(self) -> str:
        return self.clock().astimezone(timezone.utc).isoformat()

    def _policy_bytes(self) -> bytes:
        return _canonical_json({
            "metric_epsilon": self.policy.metric_epsilon,
            "min_primary_improvement": self.policy.min_primary_improvement,
            "latency_absolute_tolerance_ms": self.policy.latency_absolute_tolerance_ms,
            "latency_relative_tolerance": self.policy.latency_relative_tolerance,
        })

    @staticmethod
    def _baseline_from_bytes(content: bytes) -> EvalReport:
        payload = json.loads(content.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("experiment baseline must be a JSON object")
        return EvalReport.from_dict(payload)

    def run(
        self,
        candidate: ExperimentCandidate,
        executor: CandidateExperimentExecutor,
    ) -> ExperimentResult:
        if candidate.status != "PROPOSED":
            raise ValueError("only a PROPOSED improvement candidate can be experimented")
        if not getattr(executor, "executor_id", "").strip():
            raise ValueError("experiment executor_id cannot be empty")

        golden_bytes = self.golden_tasks_path.read_bytes()
        baseline_bytes = self.baseline_path.read_bytes()
        policy_bytes = self._policy_bytes()
        suite = load_golden_suite(self.golden_tasks_path)
        baseline = self._baseline_from_bytes(baseline_bytes)
        if baseline.suite_id != suite.suite_id or baseline.suite_digest != suite.digest:
            raise ValueError("baseline is not bound to the exact Golden Eval suite")

        candidate_manifest = tuple(
            SnapshotArtifact(
                "CANDIDATE",
                artifact.relative_path,
                _sha256(artifact.content),
                len(artifact.content),
                artifact.media_type,
            )
            for artifact in sorted(candidate.artifacts, key=lambda item: item.relative_path)
        )
        candidate_fingerprint = _sha256(_canonical_json({
            "candidate_id": candidate.candidate_id,
            "description": candidate.description,
            "status": candidate.status,
            "source_lesson_id": candidate.source_lesson_id,
            "source_confidence": candidate.source_confidence,
            "executor_id": executor.executor_id,
            "artifacts": [asdict(item) for item in candidate_manifest],
        }))
        baseline_digest = _sha256(baseline_bytes)
        policy_digest = _sha256(policy_bytes)
        contract_digest = _sha256(
            _canonical_json({
                "suite_digest": suite.digest,
                "baseline_digest": baseline_digest,
                "policy_digest": policy_digest,
            })
        )
        experiment_id = f"experiment-{uuid4()}"
        created_at = self._timestamp()
        snapshot_payload = {
            "experiment_id": experiment_id,
            "candidate_id": candidate.candidate_id,
            "candidate_description": candidate.description,
            "source_lesson_id": candidate.source_lesson_id,
            "source_confidence": candidate.source_confidence,
            "candidate_fingerprint": candidate_fingerprint,
            "executor_id": executor.executor_id,
            "suite_id": suite.suite_id,
            "suite_digest": suite.digest,
            "baseline_digest": baseline_digest,
            "policy_digest": policy_digest,
            "contract_digest": contract_digest,
            "created_at": created_at,
            "artifacts": [asdict(item) for item in candidate_manifest],
        }
        snapshot_digest = _sha256(_canonical_json(snapshot_payload))
        snapshot = ExperimentSnapshot(
            experiment_id=experiment_id,
            candidate_id=candidate.candidate_id,
            candidate_description=candidate.description,
            source_lesson_id=candidate.source_lesson_id,
            source_confidence=candidate.source_confidence,
            candidate_fingerprint=candidate_fingerprint,
            executor_id=executor.executor_id,
            suite_id=suite.suite_id,
            suite_digest=suite.digest,
            baseline_digest=baseline_digest,
            policy_digest=policy_digest,
            contract_digest=contract_digest,
            snapshot_digest=snapshot_digest,
            created_at=created_at,
            artifacts=candidate_manifest,
        )
        self.store.create(snapshot)
        self.store.add_event(experiment_id, "snapshot_created", snapshot_digest, self._timestamp())

        contract_artifacts = (
            ExperimentArtifact("golden_tasks.json", golden_bytes, "application/json"),
            ExperimentArtifact("golden_baseline.json", baseline_bytes, "application/json"),
            ExperimentArtifact("promotion_policy.json", policy_bytes, "application/json"),
        )
        for artifact in contract_artifacts:
            self.store.add_artifact(experiment_id, "CONTRACT", artifact, self._timestamp())
        for artifact in candidate.artifacts:
            self.store.add_artifact(experiment_id, "CANDIDATE", artifact, self._timestamp())
        self.store.start(experiment_id, self._timestamp())

        try:
            output_artifacts: tuple[ExperimentArtifact, ...]
            with tempfile.TemporaryDirectory(dir=self.sandbox_root) as temporary:
                sandbox = ExperimentSandbox(Path(temporary), candidate.artifacts)
                self.store.add_event(
                    experiment_id,
                    "sandbox_created",
                    "private candidate workspace created",
                    self._timestamp(),
                )
                self.store.add_event(
                    experiment_id,
                    "baseline_loaded",
                    baseline.run_id,
                    self._timestamp(),
                )
                candidate_report = GoldenEvalRunner(suite).run(
                    _SandboxedExecutorAdapter(executor, sandbox),
                    run_id=experiment_id,
                    created_at=self._timestamp(),
                )
                self.store.add_event(
                    experiment_id,
                    "candidate_evaluated",
                    f"tasks={len(candidate_report.tasks)}",
                    self._timestamp(),
                )
                output_artifacts = sandbox.output_artifacts()
            self.store.add_event(
                experiment_id,
                "sandbox_destroyed",
                "private candidate workspace removed",
                self._timestamp(),
            )

            if self.golden_tasks_path.read_bytes() != golden_bytes:
                raise RuntimeError("Golden Tasks changed during candidate experiment")
            if self.baseline_path.read_bytes() != baseline_bytes:
                raise RuntimeError("Golden baseline changed during candidate experiment")
            if self._policy_bytes() != policy_bytes:
                raise RuntimeError("promotion policy changed during candidate experiment")
            self.store.add_event(
                experiment_id,
                "contract_verified",
                contract_digest,
                self._timestamp(),
            )

            comparison = self.policy.compare(
                baseline,
                candidate_report,
                candidate.candidate_id,
                candidate.description,
            )
            self.store.add_event(
                experiment_id,
                "metrics_compared",
                comparison.decision.status,
                self._timestamp(),
            )
            decision_map = {
                "REJECTED_REGRESSION": "REJECT",
                "NO_PROMOTION": "NO_IMPROVEMENT",
                "ELIGIBLE_FOR_EXPLICIT_APPROVAL": "ELIGIBLE_FOR_APPROVAL",
            }
            decision = decision_map[comparison.decision.status]

            for artifact in output_artifacts:
                self.store.add_artifact(experiment_id, "OUTPUT", artifact, self._timestamp())
            comparison_bytes = json.dumps(
                comparison.to_dict(), indent=2, sort_keys=True
            ).encode("utf-8")
            self.store.add_artifact(
                experiment_id,
                "REPORT",
                ExperimentArtifact("comparison.json", comparison_bytes, "application/json"),
                self._timestamp(),
            )
            self.store.add_event(
                experiment_id,
                "artifacts_persisted",
                f"outputs={len(output_artifacts)}; reports=1",
                self._timestamp(),
            )
            self.store.add_event(
                experiment_id,
                "decision_recorded",
                decision,
                self._timestamp(),
            )
            self.store.complete(
                experiment_id,
                decision,
                baseline,
                candidate_report,
                comparison.to_dict(),
                self._timestamp(),
            )
        except Exception as exc:
            self.store.add_event(
                experiment_id,
                "experiment_failed",
                f"{type(exc).__name__}: {exc}",
                self._timestamp(),
            )
            self.store.fail(experiment_id, f"{type(exc).__name__}: {exc}", self._timestamp())
            raise

        artifacts = self.store.list_artifacts(experiment_id)
        trace = self.store.list_events(experiment_id)
        return ExperimentResult(
            experiment_id=experiment_id,
            candidate_id=candidate.candidate_id,
            decision=decision,
            promotion_status=comparison.decision.status,
            snapshot_digest=snapshot_digest,
            suite_digest=suite.digest,
            baseline_metrics=baseline.metrics,
            candidate_metrics=candidate_report.metrics,
            regressions=comparison.decision.regressions,
            improvements=comparison.decision.improvements,
            requires_explicit_approval=decision == "ELIGIBLE_FOR_APPROVAL",
            automatic_change_applied=False,
            trace=trace,
            artifact_hashes=tuple(item.sha256 for item in artifacts),
        )
