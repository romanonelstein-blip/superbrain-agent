from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import uuid4

from .assurance import IntelligenceAssurance
from .cognition import ContextItem, ContextManager, RecoveryController
from .persistence import SQLiteStateStore
from .world_model import BeliefState, WorldModel


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AutonomyGuardError(RuntimeError):
    pass


@dataclass(frozen=True)
class AutonomyPolicy:
    max_missions_per_cycle: int = 3
    max_rounds_per_mission: int = 3
    max_sources_per_mission: int = 12
    min_assurance_score: float = 0.70
    allow_high_impact_actions: bool = False

    def validate(self) -> None:
        if not 1 <= self.max_missions_per_cycle <= 10:
            raise ValueError("max_missions_per_cycle must be between 1 and 10")
        if not 1 <= self.max_rounds_per_mission <= 8:
            raise ValueError("max_rounds_per_mission must be between 1 and 8")
        if not 1 <= self.max_sources_per_mission <= 50:
            raise ValueError("max_sources_per_mission must be between 1 and 50")
        if not 0.0 <= self.min_assurance_score <= 1.0:
            raise ValueError("min_assurance_score must be between 0 and 1")


@dataclass(frozen=True)
class AutonomyStep:
    mission: str
    run_id: str
    nexus_value: str
    assurance_status: str
    assurance_score: float
    belief_state: str | None
    belief_confidence: float | None
    change_event_type: str | None
    stop_reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AutonomyCycle:
    cycle_id: str
    status: str
    started_at: str
    finished_at: str
    steps: tuple[AutonomyStep, ...]
    next_actions: tuple[str, ...]
    blocked_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "steps": [s.to_dict() for s in self.steps],
            "next_actions": list(self.next_actions),
            "blocked_reason": self.blocked_reason,
        }


class AutonomousIntelligenceEngine:
    """Bounded autonomous intelligence loop.

    Observe -> select mission -> research -> Nexus -> revise World Model -> detect change
    -> assure -> decide whether to continue. It can propose research, but cannot execute
    high-impact external actions, mutate code/policy/provider configuration, or bypass Nexus.
    """

    def __init__(self, service: Any, *, policy: AutonomyPolicy | None = None) -> None:
        self.service = service
        self.policy = policy or AutonomyPolicy()
        self.policy.validate()
        self.context_manager = ContextManager()
        self.recovery = RecoveryController()

    def _observe(self) -> tuple[dict[str, Any], ...]:
        with SQLiteStateStore(self.service.database_path) as store:
            beliefs = WorldModel(store).list(limit=100)
        # Weak or unresolved beliefs become candidates for another research cycle.
        ranked = sorted(
            beliefs,
            key=lambda b: (
                0 if b.state in {BeliefState.CONTESTED, BeliefState.UNCERTAIN, BeliefState.UNKNOWN} else 1,
                b.confidence,
                -b.revision_count,
            ),
        )
        return tuple(b.to_dict() for b in ranked)

    @staticmethod
    def _mission_from_belief(belief: dict[str, Any]) -> str:
        proposition = str(belief["proposition"])
        state = str(belief["state"])
        if state == BeliefState.CONTESTED.value:
            return f"Reassess the contested proposition: {proposition}. Seek strong counterevidence and independent corroboration."
        if state in {BeliefState.UNCERTAIN.value, BeliefState.UNKNOWN.value}:
            return f"Investigate the unresolved proposition: {proposition}. Find primary evidence, independent sources, and falsification evidence."
        return f"Revalidate the current belief: {proposition}. Check for material new evidence or contradiction."

    def _select_missions(self, seeds: Iterable[str] | None) -> tuple[str, ...]:
        selected: list[str] = []
        seen: set[str] = set()
        seed_items = [ContextItem(key=f"seed:{i}", text=str(mission), relevance=1.0, recency=1.0, essential=True)
                      for i, mission in enumerate(seeds or ())]
        for item in self.context_manager.select(seed_items, max_items=self.policy.max_missions_per_cycle, max_chars=12000):
            clean = " ".join(item.text.split()).strip()
            if clean and clean.casefold() not in seen:
                selected.append(clean)
                seen.add(clean.casefold())
                if len(selected) >= self.policy.max_missions_per_cycle:
                    return tuple(selected)
        for belief in self._observe():
            mission = self._mission_from_belief(belief)
            if mission.casefold() not in seen:
                selected.append(mission)
                seen.add(mission.casefold())
            if len(selected) >= self.policy.max_missions_per_cycle:
                break
        return tuple(selected)

    @staticmethod
    def _assurance_observation(detail: dict[str, Any], *, impact: str = "LOW") -> dict[str, Any]:
        evidence = detail.get("evidence", [])
        support = sum(1 for item in evidence if item.get("stance") == "support")
        challenge = sum(1 for item in evidence if item.get("stance") == "challenge")
        families = {item.get("source_family") for item in evidence if item.get("source_family")}
        sources = {item.get("source_id") for item in evidence if item.get("source_id")}
        quality = (
            sum(float(item.get("reliability", 0.0)) * float(item.get("freshness", 0.0)) * float(item.get("relevance", 0.0)) for item in evidence)
            / len(evidence)
            if evidence else 0.0
        )
        belief = detail.get("world_model") or {}
        return {
            "evidence_count": len(evidence),
            "decision": detail.get("run", {}).get("final_value") or "UNRESOLVED",
            "source_count": len(sources),
            "unique_family_count": len(families),
            "independence_warning": len(sources) >= 3 and len(families) <= 1,
            "support": support,
            "challenge": challenge,
            "belief_state": belief.get("state", "UNKNOWN"),
            "evidence_quality": quality,
            "confidence": float(belief.get("confidence", 0.0)),
            "all_accepted_have_provenance": all(bool(item.get("citation")) and bool(item.get("content_hash")) for item in evidence),
            "previous_state": None,
            "current_state": belief.get("state", "UNKNOWN"),
            "impact": impact,
            "human_authorized": False,
        }

    def run_cycle(self, seeds: Iterable[str] | None = None, *, cycle_id: str | None = None) -> AutonomyCycle:
        cycle_id = cycle_id or f"autonomy-{uuid4()}"
        started = _utc_now()
        missions = self._select_missions(seeds)
        if not missions:
            finished = _utc_now()
            result = AutonomyCycle(cycle_id, "NO_WORK", started, finished, (), (), "no research candidates available")
            self._persist_cycle(result)
            return result

        steps: list[AutonomyStep] = []
        next_actions: list[str] = []
        blocked: str | None = None
        for mission in missions:
            run_id = f"{cycle_id}-{hashlib.sha256(mission.encode()).hexdigest()[:12]}"
            try:
                checkpoint = self.service.get_mission(run_id)
                recovery = self.recovery.run(
                    lambda: self.service.execute_deep_research_mission(
                        mission,
                        run_id=run_id,
                        max_rounds=self.policy.max_rounds_per_mission,
                        max_total_sources=self.policy.max_sources_per_mission,
                    ),
                    checkpoint=checkpoint,
                    max_retries=1,
                )
                if recovery.status == "FAILED":
                    raise AutonomyGuardError("recovery exhausted without a valid checkpoint")
                result = recovery.value
                detail = self.service.get_mission(run_id) or checkpoint
                if detail is None:
                    raise AutonomyGuardError("mission completed without durable mission detail")
                observation = self._assurance_observation(detail)
                assurance = self.service.run_assurance(observation, run_id=f"{run_id}-assurance")
                assurance_score = float(assurance["score"])
                belief = detail.get("world_model") or {}
                change = self._latest_change(run_id)
                stop_reason = result.research.get("stop_reason") if isinstance(result.research, dict) else None
                steps.append(AutonomyStep(
                    mission=mission,
                    run_id=run_id,
                    nexus_value=result.nexus_final_value,
                    assurance_status=str(assurance["status"]),
                    assurance_score=assurance_score,
                    belief_state=belief.get("state"),
                    belief_confidence=belief.get("confidence"),
                    change_event_type=change.get("event_type") if change else None,
                    stop_reason=stop_reason,
                ))
                if assurance_score < self.policy.min_assurance_score or assurance["status"] != "PASS":
                    blocked = f"assurance gate blocked autonomous continuation for {run_id}"
                    next_actions.append("ESCALATE_TO_MASTER")
                    break
                if change and change.get("severity") == "HIGH":
                    next_actions.append(f"REVIEW_HIGH_SEVERITY_CHANGE:{change['change_id']}")
            except Exception as exc:
                blocked = f"autonomous step blocked: {type(exc).__name__}"
                next_actions.append("RESEARCH_MORE_OR_ESCALATE")
                break

        status = "COMPLETED" if blocked is None else "BLOCKED"
        if not next_actions and steps:
            next_actions.append("CONTINUE_MONITORING")
        finished = _utc_now()
        result = AutonomyCycle(cycle_id, status, started, finished, tuple(steps), tuple(next_actions), blocked)
        self._persist_cycle(result)
        return result

    def _latest_change(self, run_id: str) -> dict[str, Any] | None:
        changes = self.service.list_changes(limit=100)
        for change in changes:
            if change.get("run_id") == run_id:
                return change
        return None

    def _persist_cycle(self, result: AutonomyCycle) -> None:
        with SQLiteStateStore(self.service.database_path) as store:
            store.add_autonomy_cycle(result.cycle_id, result.to_dict(), result.started_at)

    def list_cycles(self, limit: int = 20) -> tuple[dict[str, Any], ...]:
        with SQLiteStateStore(self.service.database_path) as store:
            return tuple(store.list_autonomy_cycles(limit))
