from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Callable, Any


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    initial_backoff_seconds: float = 0.0
    backoff_multiplier: float = 2.0
    retryable_exceptions: tuple[type[BaseException], ...] = (Exception,)

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.initial_backoff_seconds < 0:
            raise ValueError("initial_backoff_seconds must be >= 0")
        if self.backoff_multiplier < 1:
            raise ValueError("backoff_multiplier must be >= 1")


@dataclass(frozen=True)
class StepDefinition:
    step_id: str
    idempotency_key: str
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)


@dataclass
class StepState:
    step_id: str
    idempotency_key: str
    status: str = "pending"  # pending|running|completed|failed
    attempts: int = 0
    result: Any = None
    error: str | None = None


@dataclass
class WorkflowState:
    run_id: str
    status: str = "pending"  # pending|running|completed|failed
    current_step: str | None = None
    steps: dict[str, StepState] = field(default_factory=dict)
    version: int = 1


class CheckpointStore:
    """
    Simple atomic JSON checkpoint store for the prototype.
    Production backends can replace this with Postgres/Temporal/etc.
    """

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, run_id: str) -> Path:
        safe = "".join(ch for ch in run_id if ch.isalnum() or ch in ("-", "_"))
        if not safe:
            raise ValueError("invalid run_id")
        return self.directory / f"{safe}.json"

    def save(self, state: WorkflowState) -> None:
        path = self._path(state.run_id)
        tmp = path.with_suffix(".tmp")
        payload = {
            "run_id": state.run_id,
            "status": state.status,
            "current_step": state.current_step,
            "version": state.version,
            "steps": {k: asdict(v) for k, v in state.steps.items()},
        }
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)

    def load(self, run_id: str) -> WorkflowState | None:
        path = self._path(run_id)
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        state = WorkflowState(
            run_id=raw["run_id"],
            status=raw["status"],
            current_step=raw.get("current_step"),
            version=raw.get("version", 1),
        )
        state.steps = {
            key: StepState(**value)
            for key, value in raw.get("steps", {}).items()
        }
        return state


class IdempotencyLedger:
    """
    Tracks completed idempotency keys. A completed step will never be executed
    again during a resumed run with the same state.
    """

    def __init__(self) -> None:
        self.completed: dict[str, Any] = {}

    def has(self, key: str) -> bool:
        return key in self.completed

    def get(self, key: str) -> Any:
        return self.completed[key]

    def record(self, key: str, result: Any) -> None:
        self.completed[key] = result


class DurableWorkflow:
    def __init__(
        self,
        run_id: str,
        steps: list[StepDefinition],
        store: CheckpointStore,
        ledger: IdempotencyLedger | None = None,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        self.run_id = run_id
        self.steps = steps
        self.store = store
        self.ledger = ledger or IdempotencyLedger()
        self.sleep_fn = sleep_fn or time.sleep

    def _load_or_init(self) -> WorkflowState:
        state = self.store.load(self.run_id)
        if state is not None:
            # Rebuild ledger from completed checkpointed steps.
            for step_state in state.steps.values():
                if step_state.status == "completed":
                    self.ledger.record(step_state.idempotency_key, step_state.result)
            return state

        state = WorkflowState(run_id=self.run_id)
        state.steps = {
            step.step_id: StepState(
                step_id=step.step_id,
                idempotency_key=step.idempotency_key,
            )
            for step in self.steps
        }
        self.store.save(state)
        return state

    def run(
        self,
        handlers: dict[str, Callable[[WorkflowState], Any]],
        crash_after_step: str | None = None,
    ) -> WorkflowState:
        state = self._load_or_init()
        state.status = "running"
        self.store.save(state)

        for definition in self.steps:
            ss = state.steps[definition.step_id]
            state.current_step = definition.step_id

            if ss.status == "completed":
                continue

            if self.ledger.has(definition.idempotency_key):
                ss.status = "completed"
                ss.result = self.ledger.get(definition.idempotency_key)
                ss.error = None
                self.store.save(state)
                continue

            if definition.step_id not in handlers:
                ss.status = "failed"
                ss.error = "missing handler"
                state.status = "failed"
                self.store.save(state)
                return state

            handler = handlers[definition.step_id]
            backoff = definition.retry_policy.initial_backoff_seconds
            last_error: BaseException | None = None

            # Attempts are checkpointed before entering the handler, including
            # attempts interrupted by process termination. Restarting must not
            # grant a fresh retry budget.
            remaining_attempts = definition.retry_policy.max_attempts - ss.attempts
            if remaining_attempts <= 0:
                ss.status = "failed"
                ss.error = ss.error or "retry budget exhausted before resume"
                state.status = "failed"
                self.store.save(state)
                return state

            for _ in range(remaining_attempts):
                ss.status = "running"
                ss.attempts += 1
                self.store.save(state)

                try:
                    result = handler(state)
                    ss.status = "completed"
                    ss.result = result
                    ss.error = None
                    self.ledger.record(definition.idempotency_key, result)
                    self.store.save(state)
                    last_error = None
                    break
                except definition.retry_policy.retryable_exceptions as exc:
                    last_error = exc
                    ss.error = f"{type(exc).__name__}: {exc}"
                    self.store.save(state)
                    if ss.attempts < definition.retry_policy.max_attempts and backoff > 0:
                        self.sleep_fn(backoff)
                        backoff *= definition.retry_policy.backoff_multiplier
                except BaseException as exc:
                    last_error = exc
                    ss.error = f"{type(exc).__name__}: {exc}"
                    self.store.save(state)
                    break

            if last_error is not None:
                ss.status = "failed"
                state.status = "failed"
                self.store.save(state)
                return state

            if crash_after_step == definition.step_id:
                # Simulated process crash after a durable checkpoint.
                raise RuntimeError(f"simulated crash after {definition.step_id}")

        state.current_step = None
        state.status = "completed"
        self.store.save(state)
        return state
