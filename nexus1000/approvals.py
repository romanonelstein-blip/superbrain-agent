from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable, Protocol
from uuid import uuid4

from .evals import EvalReport, GoldenEvalRunner, PromotionPolicy, load_golden_suite
from .experiments import SQLiteExperimentStore, StoredArtifact


APPROVAL_INTENT = "I explicitly approve this exact immutable SB-019 experiment for one controlled local apply."


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _safe_path(value: str) -> PurePosixPath:
    if not value or "\\" in value:
        raise ValueError("apply paths must be non-empty POSIX relative paths")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"unsafe apply path: {value}")
    return path


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ApprovalRecord:
    approval_id: str
    experiment_id: str
    snapshot_digest: str
    candidate_id: str
    suite_digest: str
    approver_id: str
    signer_kind: str
    intent: str
    nonce: str
    issued_at: str
    payload_digest: str
    signature: str


class HumanApprovalSigner:
    """Creates verifiable human approval records; never used by the apply engine itself."""

    def __init__(self, secret: bytes) -> None:
        if len(secret) < 32:
            raise ValueError("approval signing secret must contain at least 32 bytes")
        self._secret = secret

    def issue(
        self,
        *,
        experiment_id: str,
        snapshot_digest: str,
        candidate_id: str,
        suite_digest: str,
        approver_id: str,
        intent: str,
        signer_kind: str = "HUMAN",
        nonce: str | None = None,
        issued_at: str | None = None,
    ) -> ApprovalRecord:
        if signer_kind != "HUMAN":
            raise ValueError("AI, agent, service, and automated approvals are forbidden")
        if intent != APPROVAL_INTENT:
            raise ValueError("exact explicit human approval intent is required")
        if not approver_id.strip():
            raise ValueError("approver_id is required")
        payload = {
            "experiment_id": experiment_id,
            "snapshot_digest": snapshot_digest,
            "candidate_id": candidate_id,
            "suite_digest": suite_digest,
            "approver_id": approver_id,
            "signer_kind": signer_kind,
            "intent": intent,
            "nonce": nonce or uuid4().hex,
            "issued_at": issued_at or _utc_now().isoformat(),
        }
        payload_digest = _sha256(_canonical_json(payload))
        signature = hmac.new(self._secret, payload_digest.encode("ascii"), hashlib.sha256).hexdigest()
        return ApprovalRecord(
            approval_id=f"approval-{payload_digest}",
            payload_digest=payload_digest,
            signature=signature,
            **payload,
        )

    def verify(self, approval: ApprovalRecord) -> bool:
        payload = {
            key: getattr(approval, key)
            for key in (
                "experiment_id", "snapshot_digest", "candidate_id", "suite_digest",
                "approver_id", "signer_kind", "intent", "nonce", "issued_at",
            )
        }
        digest = _sha256(_canonical_json(payload))
        expected = hmac.new(self._secret, digest.encode("ascii"), hashlib.sha256).hexdigest()
        return (
            approval.approval_id == f"approval-{digest}"
            and approval.payload_digest == digest
            and approval.signer_kind == "HUMAN"
            and approval.intent == APPROVAL_INTENT
            and hmac.compare_digest(approval.signature, expected)
        )


@dataclass(frozen=True)
class ApplyOperation:
    path: str
    source_artifact: str
    expected_before_sha256: str


@dataclass(frozen=True)
class ApplyResult:
    transaction_id: str
    experiment_id: str
    approval_id: str
    status: str
    pre_apply_snapshot_digest: str
    post_apply_report: EvalReport | None
    rollback_verified: bool
    regressions: tuple[str, ...]
    applied_paths: tuple[str, ...]


class GoldenExecutor(Protocol):
    executor_id: str

    def execute(self, task): ...


class SQLiteApplyStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS approvals (
                approval_id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL,
                snapshot_digest TEXT NOT NULL, candidate_id TEXT NOT NULL,
                suite_digest TEXT NOT NULL, record_json TEXT NOT NULL,
                payload_digest TEXT NOT NULL UNIQUE, signature TEXT NOT NULL,
                consumed_by TEXT UNIQUE, consumed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS apply_transactions (
                transaction_id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL,
                approval_id TEXT NOT NULL UNIQUE REFERENCES approvals(approval_id),
                status TEXT NOT NULL CHECK(status IN ('APPLYING','APPLIED','ROLLED_BACK','FAILED')),
                pre_snapshot_digest TEXT NOT NULL, pre_snapshot_json TEXT NOT NULL,
                post_report_json TEXT, regressions_json TEXT NOT NULL DEFAULT '[]',
                rollback_verified INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL, completed_at TEXT, error TEXT
            );
            CREATE TABLE IF NOT EXISTS apply_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_id TEXT NOT NULL REFERENCES apply_transactions(transaction_id),
                stage TEXT NOT NULL, detail TEXT NOT NULL, occurred_at TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS approvals_no_delete BEFORE DELETE ON approvals
            BEGIN SELECT RAISE(ABORT, 'approval records are append-only'); END;
            CREATE TRIGGER IF NOT EXISTS approvals_core_immutable
            BEFORE UPDATE OF approval_id, experiment_id, snapshot_digest, candidate_id,
                suite_digest, record_json, payload_digest, signature ON approvals
            BEGIN SELECT RAISE(ABORT, 'approval record is immutable'); END;
            CREATE TRIGGER IF NOT EXISTS approvals_consume_once
            BEFORE UPDATE OF consumed_by, consumed_at ON approvals WHEN OLD.consumed_by IS NOT NULL
            BEGIN SELECT RAISE(ABORT, 'approval is single-use'); END;
            CREATE TRIGGER IF NOT EXISTS transactions_no_delete BEFORE DELETE ON apply_transactions
            BEGIN SELECT RAISE(ABORT, 'apply transactions are append-only'); END;
            CREATE TRIGGER IF NOT EXISTS transactions_terminal_immutable BEFORE UPDATE ON apply_transactions
            WHEN OLD.status IN ('APPLIED','ROLLED_BACK','FAILED')
            BEGIN SELECT RAISE(ABORT, 'terminal apply transaction is immutable'); END;
            CREATE TRIGGER IF NOT EXISTS apply_events_no_update BEFORE UPDATE ON apply_events
            BEGIN SELECT RAISE(ABORT, 'apply events are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS apply_events_no_delete BEFORE DELETE ON apply_events
            BEGIN SELECT RAISE(ABORT, 'apply events are append-only'); END;
            CREATE TRIGGER IF NOT EXISTS apply_events_terminal_insert BEFORE INSERT ON apply_events
            WHEN (SELECT status FROM apply_transactions WHERE transaction_id=NEW.transaction_id)
                IN ('APPLIED','ROLLED_BACK','FAILED')
            BEGIN SELECT RAISE(ABORT, 'terminal apply transaction cannot receive events'); END;
        """)
        self.conn.commit()

    def register_and_consume(
        self, approval: ApprovalRecord, transaction_id: str, pre_digest: str,
        pre_json: str, created_at: str,
    ) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO approvals VALUES (?,?,?,?,?,?,?,?,NULL,NULL)",
                (approval.approval_id, approval.experiment_id, approval.snapshot_digest,
                 approval.candidate_id, approval.suite_digest,
                 json.dumps(asdict(approval), sort_keys=True, separators=(",", ":")),
                 approval.payload_digest, approval.signature),
            )
            cursor = self.conn.execute(
                "UPDATE approvals SET consumed_by=?, consumed_at=? WHERE approval_id=? AND consumed_by IS NULL",
                (transaction_id, created_at, approval.approval_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("approval has already been consumed")
            self.conn.execute(
                "INSERT INTO apply_transactions VALUES (?,?,?,'APPLYING',?,?,NULL,'[]',0,?,NULL,NULL)",
                (transaction_id, approval.experiment_id, approval.approval_id,
                 pre_digest, pre_json, created_at),
            )

    def event(self, transaction_id: str, stage: str, detail: str, at: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO apply_events(transaction_id,stage,detail,occurred_at) VALUES(?,?,?,?)",
                (transaction_id, stage, detail, at),
            )

    def finish(self, transaction_id: str, status: str, report: EvalReport | None,
               regressions: tuple[str, ...], rollback_verified: bool, at: str,
               error: str | None = None) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE apply_transactions SET status=?,post_report_json=?,regressions_json=?,"
                "rollback_verified=?,completed_at=?,error=? WHERE transaction_id=? AND status='APPLYING'",
                (status, json.dumps(report.to_dict(), sort_keys=True) if report else None,
                 json.dumps(regressions), int(rollback_verified), at, error, transaction_id),
            )

    def transaction(self, transaction_id: str) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM apply_transactions WHERE transaction_id=?", (transaction_id,)).fetchone()
        if row is None: raise KeyError(transaction_id)
        return row

    def events(self, transaction_id: str) -> tuple[sqlite3.Row, ...]:
        return tuple(self.conn.execute("SELECT * FROM apply_events WHERE transaction_id=? ORDER BY sequence", (transaction_id,)))

    def approval_consumed(self, approval_id: str) -> bool:
        row = self.conn.execute(
            "SELECT consumed_by FROM approvals WHERE approval_id=?", (approval_id,)
        ).fetchone()
        return row is not None and row["consumed_by"] is not None

    def __enter__(self): return self
    def __exit__(self, *_): self.conn.close()


class ApprovalGatedApplyEngine:
    def __init__(self, *, experiment_store: SQLiteExperimentStore, apply_store: SQLiteApplyStore,
                 signer: HumanApprovalSigner, workspace: str | Path,
                 golden_tasks_path: str | Path, executor_factory: Callable[[Path], GoldenExecutor],
                 policy: PromotionPolicy | None = None,
                 clock: Callable[[], datetime] | None = None) -> None:
        self.experiment_store = experiment_store
        self.apply_store = apply_store
        self.signer = signer
        self.workspace = Path(workspace).resolve()
        self.golden_tasks_path = Path(golden_tasks_path)
        self.executor_factory = executor_factory
        self.policy = policy or PromotionPolicy()
        self.clock = clock or _utc_now

    def _now(self) -> str: return self.clock().astimezone(timezone.utc).isoformat()

    @staticmethod
    def _artifact_map(artifacts: tuple[StoredArtifact, ...]) -> dict[str, StoredArtifact]:
        return {a.relative_path: a for a in artifacts if a.role == "CANDIDATE"}

    def _plan(self, artifacts: dict[str, StoredArtifact]) -> tuple[ApplyOperation, ...]:
        if "apply-plan.json" not in artifacts:
            raise ValueError("eligible experiment contains no declarative apply plan")
        payload = json.loads(artifacts["apply-plan.json"].content)
        if payload.get("schema_version") != "sb020.apply.v1":
            raise ValueError("unsupported apply plan schema")
        if set(payload) != {"schema_version", "operations"}:
            raise ValueError("apply plan contains executable or unsupported fields")
        operations = payload["operations"]
        if not isinstance(operations, list) or not 1 <= len(operations) <= 20:
            raise ValueError("apply plan must contain 1 to 20 operations")
        result = []
        for raw in operations:
            if set(raw) != {"op", "path", "source_artifact", "expected_before_sha256"} or raw["op"] != "replace":
                raise ValueError("only declarative replace operations are allowed")
            path = _safe_path(raw["path"]).as_posix()
            source = _safe_path(raw["source_artifact"]).as_posix()
            if source not in artifacts or source == "apply-plan.json":
                raise ValueError("apply source artifact is missing")
            result.append(ApplyOperation(path, source, raw["expected_before_sha256"]))
        if len({op.path for op in result}) != len(result):
            raise ValueError("apply target paths must be unique")
        return tuple(result)

    def apply(self, experiment_id: str, approval: ApprovalRecord) -> ApplyResult:
        if not self.signer.verify(approval): raise ValueError("approval signature or human attestation is invalid")
        experiment = self.experiment_store.get_experiment(experiment_id)
        if experiment.status != "COMPLETED" or experiment.decision != "ELIGIBLE_FOR_APPROVAL":
            raise ValueError("only a completed ELIGIBLE_FOR_APPROVAL experiment can be applied")
        snapshot = experiment.snapshot
        expected_binding = (experiment_id, experiment.snapshot_digest, experiment.candidate_id, snapshot["suite_digest"])
        actual_binding = (approval.experiment_id, approval.snapshot_digest, approval.candidate_id, approval.suite_digest)
        if actual_binding != expected_binding: raise ValueError("approval is not bound to this immutable experiment")
        if self.apply_store.approval_consumed(approval.approval_id):
            raise ValueError("approval has already been consumed")
        suite = load_golden_suite(self.golden_tasks_path)
        if suite.digest != approval.suite_digest: raise ValueError("Golden suite changed after approval")
        artifacts = self._artifact_map(self.experiment_store.list_artifacts(experiment_id))
        operations = self._plan(artifacts)
        before: dict[str, bytes] = {}
        for operation in operations:
            target = self.workspace.joinpath(*PurePosixPath(operation.path).parts).resolve()
            if self.workspace not in target.parents or not target.is_file() or target.is_symlink():
                raise ValueError(f"apply target must be an existing regular file inside workspace: {operation.path}")
            content = target.read_bytes()
            if _sha256(content) != operation.expected_before_sha256:
                raise ValueError(f"precondition hash mismatch: {operation.path}")
            before[operation.path] = content
        pre_payload = {path: _sha256(content) for path, content in sorted(before.items())}
        pre_digest = _sha256(_canonical_json(pre_payload))
        transaction_id = f"apply-{uuid4()}"
        self.apply_store.register_and_consume(approval, transaction_id, pre_digest,
                                               json.dumps(pre_payload, sort_keys=True), self._now())
        self.apply_store.event(transaction_id, "approval_verified", approval.payload_digest, self._now())
        self.apply_store.event(transaction_id, "pre_apply_snapshot_created", pre_digest, self._now())
        applied: list[str] = []
        report = None
        regressions: tuple[str, ...] = ()
        try:
            for operation in operations:
                target = self.workspace.joinpath(*PurePosixPath(operation.path).parts)
                replacement = artifacts[operation.source_artifact].content
                fd, temp_name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.")
                try:
                    with os.fdopen(fd, "wb") as handle:
                        handle.write(replacement); handle.flush(); os.fsync(handle.fileno())
                    os.replace(temp_name, target)
                finally:
                    if os.path.exists(temp_name): os.unlink(temp_name)
                applied.append(operation.path)
            self.apply_store.event(transaction_id, "declarative_apply_completed", ",".join(applied), self._now())
            report = GoldenEvalRunner(suite).run(self.executor_factory(self.workspace), run_id=transaction_id)
            if experiment.candidate_report is None: raise RuntimeError("eligible experiment lacks candidate report")
            decision = self.policy.evaluate(experiment.candidate_report, report, experiment.candidate_id,
                                            "post-apply realization check")
            regressions = decision.regressions
            self.apply_store.event(transaction_id, "post_apply_golden_evals", decision.status, self._now())
            if regressions:
                raise RuntimeError("post-apply Golden Eval regression")
            self.apply_store.event(transaction_id, "transaction_committed", report.suite_digest, self._now())
            self.apply_store.finish(transaction_id, "APPLIED", report, (), False, self._now())
            return ApplyResult(transaction_id, experiment_id, approval.approval_id, "APPLIED",
                               pre_digest, report, False, (), tuple(applied))
        except Exception as exc:
            for path, content in before.items():
                target = self.workspace.joinpath(*PurePosixPath(path).parts)
                target.write_bytes(content)
            rollback_verified = all(
                _sha256(self.workspace.joinpath(*PurePosixPath(path).parts).read_bytes()) == _sha256(content)
                for path, content in before.items()
            )
            self.apply_store.event(transaction_id, "rollback_completed", str(rollback_verified).lower(), self._now())
            rollback_report = GoldenEvalRunner(suite).run(self.executor_factory(self.workspace), run_id=f"{transaction_id}-rollback")
            baseline = experiment.baseline_report
            rollback_decision = self.policy.evaluate(baseline, rollback_report, experiment.candidate_id,
                                                     "rollback verification") if baseline else None
            rollback_verified = rollback_verified and rollback_decision is not None and not rollback_decision.regressions
            self.apply_store.event(transaction_id, "rollback_verified", str(rollback_verified).lower(), self._now())
            status = "ROLLED_BACK" if rollback_verified else "FAILED"
            self.apply_store.finish(transaction_id, status, report or rollback_report, regressions,
                                    rollback_verified, self._now(), str(exc))
            return ApplyResult(transaction_id, experiment_id, approval.approval_id, status,
                               pre_digest, report, rollback_verified, regressions, tuple(applied))
