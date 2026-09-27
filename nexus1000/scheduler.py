from __future__ import annotations

import argparse
import json
import signal
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import uuid4

from .autonomy import AutonomousIntelligenceEngine
from .mission_control import MissionControlService
from .persistence import SQLiteStateStore


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SchedulerPolicy:
    interval_seconds: int = 900
    failure_backoff_seconds: int = 60
    max_backoff_seconds: int = 3600

    def validate(self) -> None:
        if self.interval_seconds < 1:
            raise ValueError("interval_seconds must be >= 1")
        if self.failure_backoff_seconds < 1:
            raise ValueError("failure_backoff_seconds must be >= 1")
        if self.max_backoff_seconds < self.failure_backoff_seconds:
            raise ValueError("max_backoff_seconds must be >= failure_backoff_seconds")


class DurableAutonomyScheduler:
    """Restart-safe scheduler for the canonical autonomous intelligence cycle.

    The scheduler persists its due time and last result in the same SQLite state
    database used by Mission Control. A process restart therefore does not erase
    schedule state. An external process manager is still responsible for starting
    this process after an OS/container restart.
    """

    def __init__(
        self,
        service: Any,
        *,
        job_name: str = "continuous-intelligence",
        policy: SchedulerPolicy | None = None,
        clock: Any = time.time,
    ) -> None:
        self.service = service
        self.job_name = job_name
        self.policy = policy or SchedulerPolicy()
        self.policy.validate()
        self.clock = clock
        if not getattr(service, "database_path", None):
            raise ValueError("service must expose database_path")

    def _load(self) -> dict[str, Any] | None:
        with SQLiteStateStore(self.service.database_path) as store:
            return store.get_scheduler_job(self.job_name)

    def _save(self, state: dict[str, Any]) -> dict[str, Any]:
        with SQLiteStateStore(self.service.database_path) as store:
            store.put_scheduler_job(state)
        return state

    def ensure_configured(self, *, enabled: bool = True, start_immediately: bool = False) -> dict[str, Any]:
        current = self._load()
        now = float(self.clock())
        if current is None:
            current = {
                "job_name": self.job_name,
                "enabled": enabled,
                "interval_seconds": self.policy.interval_seconds,
                "next_run_at": now if start_immediately else now + self.policy.interval_seconds,
                "last_run_at": None,
                "last_cycle_id": None,
                "consecutive_failures": 0,
                "last_error": None,
                "updated_at": _utc_now(),
            }
        else:
            current["enabled"] = enabled
            current["interval_seconds"] = self.policy.interval_seconds
            current["updated_at"] = _utc_now()
            if start_immediately:
                current["next_run_at"] = min(float(current["next_run_at"]), now)
        return self._save(current)

    def status(self) -> dict[str, Any] | None:
        return self._load()

    def run_due(self, seeds: Iterable[str] | None = None, *, force: bool = False) -> dict[str, Any]:
        state = self._load()
        if state is None:
            state = self.ensure_configured()
        now = float(self.clock())
        if not state["enabled"]:
            return {"ran": False, "reason": "disabled", "state": state}
        if not force and now < float(state["next_run_at"]):
            return {"ran": False, "reason": "not_due", "state": state}

        cycle_id = f"{self.job_name}-{uuid4()}"
        try:
            result = AutonomousIntelligenceEngine(self.service).run_cycle(seeds, cycle_id=cycle_id)
        except Exception as exc:
            failures = int(state.get("consecutive_failures", 0)) + 1
            backoff = min(
                self.policy.max_backoff_seconds,
                self.policy.failure_backoff_seconds * (2 ** (failures - 1)),
            )
            state.update(
                last_run_at=now,
                last_cycle_id=cycle_id,
                consecutive_failures=failures,
                last_error=f"{type(exc).__name__}: {exc}",
                next_run_at=now + backoff,
                updated_at=_utc_now(),
            )
            self._save(state)
            return {"ran": True, "ok": False, "cycle_id": cycle_id, "state": state}

        if result.status == "BLOCKED":
            failures = int(state.get("consecutive_failures", 0)) + 1
            backoff = min(
                self.policy.max_backoff_seconds,
                self.policy.failure_backoff_seconds * (2 ** (failures - 1)),
            )
            state.update(
                last_run_at=now,
                last_cycle_id=result.cycle_id,
                consecutive_failures=failures,
                last_error=result.blocked_reason or "autonomy cycle blocked",
                next_run_at=now + backoff,
                updated_at=_utc_now(),
            )
            self._save(state)
            return {"ran": True, "ok": False, "cycle": result.to_dict(), "state": state}

        state.update(
            last_run_at=now,
            last_cycle_id=result.cycle_id,
            consecutive_failures=0,
            last_error=None,
            next_run_at=now + self.policy.interval_seconds,
            updated_at=_utc_now(),
        )
        self._save(state)
        return {"ran": True, "ok": True, "cycle": result.to_dict(), "state": state}

    def run_forever(self, seeds: Iterable[str] | None = None, *, poll_seconds: float = 1.0) -> None:
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be > 0")
        self.ensure_configured()
        stop = False

        def _request_stop(_signum: int, _frame: Any) -> None:
            nonlocal stop
            stop = True

        previous = {}
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                previous[sig] = signal.signal(sig, _request_stop)
            except (ValueError, OSError):
                pass

        try:
            while not stop:
                self.run_due(seeds)
                time.sleep(poll_seconds)
        finally:
            for sig, handler in previous.items():
                try:
                    signal.signal(sig, handler)
                except (ValueError, OSError):
                    pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the durable SuperBrain autonomy scheduler.")
    parser.add_argument("--database", default="work/mission-control.sqlite3")
    parser.add_argument("--interval", type=int, default=900)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--start-immediately", action="store_true")
    parser.add_argument("--seed", action="append", default=[])
    args = parser.parse_args(argv)

    service = MissionControlService(args.database)
    scheduler = DurableAutonomyScheduler(
        service, policy=SchedulerPolicy(interval_seconds=args.interval)
    )
    scheduler.ensure_configured(start_immediately=args.start_immediately or args.once)
    if args.once:
        print(json.dumps(scheduler.run_due(args.seed or None, force=args.force), indent=2, sort_keys=True))
        return 0
    scheduler.run_forever(args.seed or None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
