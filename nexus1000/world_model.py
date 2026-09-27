from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Iterable

from .models import Evidence, Stance
from .persistence import SQLiteStateStore


class BeliefState(str, Enum):
    UNKNOWN = "UNKNOWN"
    SUPPORTED = "SUPPORTED"
    CONTESTED = "CONTESTED"
    REFUTED = "REFUTED"
    UNCERTAIN = "UNCERTAIN"


@dataclass(frozen=True)
class BeliefRecord:
    belief_id: str
    proposition: str
    normalized_proposition: str
    state: BeliefState
    confidence: float
    support_strength: float
    challenge_strength: float
    evidence_count: int
    unique_source_count: int
    unique_family_count: int
    freshness: float
    last_run_id: str | None
    first_seen_at: str
    last_updated_at: str
    revision_count: int

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["state"] = self.state.value
        return payload


@dataclass(frozen=True)
class BeliefRevision:
    belief: BeliefRecord
    added_evidence_ids: tuple[str, ...]
    previous_state: BeliefState | None
    previous_confidence: float | None
    changed: bool
    reason: str

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["belief"] = self.belief.to_dict()
        payload["previous_state"] = self.previous_state.value if self.previous_state else None
        return payload


class WorldModel:
    """Persistent, evidence-weighted belief ledger.

    The world model is descriptive memory, not a second final-decision engine.
    It accumulates novel evidence for a proposition across missions and revises
    confidence deterministically. NexusOrchestrator remains authoritative for
    mission decisions.
    """

    def __init__(
        self,
        store: SQLiteStateStore,
        *,
        support_threshold: float = 0.72,
        refute_threshold: float = 0.28,
        dominance_ratio: float = 1.20,
    ) -> None:
        if not 0.5 < support_threshold < 1.0:
            raise ValueError("support_threshold must be between 0.5 and 1")
        if not 0.0 < refute_threshold < 0.5:
            raise ValueError("refute_threshold must be between 0 and 0.5")
        if dominance_ratio <= 1.0:
            raise ValueError("dominance_ratio must be greater than 1")
        self.store = store
        self.support_threshold = support_threshold
        self.refute_threshold = refute_threshold
        self.dominance_ratio = dominance_ratio

    @staticmethod
    def normalize_proposition(proposition: str) -> str:
        normalized = " ".join(proposition.casefold().split())
        normalized = re.sub(r"[^\w\s:/?.-]", "", normalized, flags=re.UNICODE)
        return normalized.strip()

    @classmethod
    def belief_id_for(cls, proposition: str) -> str:
        normalized = cls.normalize_proposition(proposition)
        if not normalized:
            raise ValueError("proposition cannot be empty")
        return "belief-" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _weight(evidence: Evidence) -> float:
        verification = 1.0 if evidence.verified else 0.35
        return evidence.reliability * evidence.freshness * evidence.relevance * verification

    def _classify(self, support: float, challenge: float, evidence_count: int) -> tuple[BeliefState, float, str]:
        total = support + challenge
        if evidence_count == 0 or total <= 0:
            return BeliefState.UNKNOWN, 0.0, "no usable evidence"
        net = (support - challenge) / total
        coverage = min(1.0, total / 2.0)
        confidence = max(0.0, min(1.0, 0.5 + (0.5 * net * coverage)))
        if support > challenge * self.dominance_ratio and confidence >= self.support_threshold:
            return BeliefState.SUPPORTED, confidence, "support dominates challenge evidence"
        if challenge > support * self.dominance_ratio and confidence <= self.refute_threshold:
            return BeliefState.REFUTED, confidence, "challenge evidence dominates support evidence"
        if support > 0 and challenge > 0:
            return BeliefState.CONTESTED, confidence, "material support and challenge evidence remain"
        return BeliefState.UNCERTAIN, confidence, "evidence is one-sided but below confidence threshold"

    def revise(
        self,
        proposition: str,
        evidence: Iterable[Evidence],
        *,
        run_id: str,
        now: str,
        excluded_evidence_ids: Iterable[str] = (),
    ) -> BeliefRevision:
        proposition = " ".join(proposition.split()).strip()
        if not proposition:
            raise ValueError("proposition cannot be empty")
        if not run_id.strip():
            raise ValueError("run_id cannot be empty")
        belief_id = self.belief_id_for(proposition)
        normalized = self.normalize_proposition(proposition)
        existing = self.store.get_world_belief(belief_id)
        previous_state = BeliefState(existing["state"]) if existing else None
        previous_confidence = float(existing["confidence"]) if existing else None
        linked = {row["evidence_id"] for row in self.store.list_world_belief_evidence(belief_id)}
        excluded = set(excluded_evidence_ids)
        additions: list[Evidence] = []
        seen: set[str] = set()
        for item in evidence:
            if item.id in linked or item.id in excluded or item.id in seen:
                continue
            seen.add(item.id)
            additions.append(item)

        if not additions and existing is None:
            # Do not create empty beliefs from a mission whose evidence was fully quarantined.
            empty = BeliefRecord(
                belief_id=belief_id,
                proposition=proposition,
                normalized_proposition=normalized,
                state=BeliefState.UNKNOWN,
                confidence=0.0,
                support_strength=0.0,
                challenge_strength=0.0,
                evidence_count=0,
                unique_source_count=0,
                unique_family_count=0,
                freshness=0.0,
                last_run_id=run_id,
                first_seen_at=now,
                last_updated_at=now,
                revision_count=0,
            )
            return BeliefRevision(
                belief=empty,
                added_evidence_ids=(),
                previous_state=None,
                previous_confidence=None,
                changed=False,
                reason="no non-quarantined evidence available",
            )

        if existing:
            support = float(existing["support_strength"])
            challenge = float(existing["challenge_strength"])
            old_count = int(existing["evidence_count"])
            first_seen = str(existing["first_seen_at"])
            revision_count = int(existing["revision_count"])
        else:
            support = 0.0
            challenge = 0.0
            old_count = 0
            first_seen = now
            revision_count = 0

        for item in additions:
            weight = self._weight(item)
            if item.stance is Stance.SUPPORT:
                support += weight
            elif item.stance is Stance.CHALLENGE:
                challenge += weight

        new_count = old_count + len(additions)
        state, confidence, reason = self._classify(support, challenge, new_count)

        linked_all = self.store.list_world_belief_evidence(belief_id)
        source_ids = set()
        families = set()
        freshness_values: list[float] = []
        for row in linked_all:
            source_row = self.store.conn.execute(
                "SELECT source_id,source_family,freshness FROM evidence WHERE evidence_id=?",
                (row["evidence_id"],),
            ).fetchone()
            if source_row:
                source_ids.add(source_row["source_id"])
                families.add(source_row["source_family"])
                freshness_values.append(float(source_row["freshness"]))
        for item in additions:
            source_ids.add(item.source_id)
            families.add(item.source_family)
            freshness_values.append(item.freshness)
        freshness = sum(freshness_values) / len(freshness_values) if freshness_values else 0.0

        changed = (
            existing is None
            or previous_state != state
            or previous_confidence is None
            or abs(previous_confidence - confidence) >= 0.01
            or bool(additions)
        )
        if changed and existing is not None:
            revision_count += 1

        record = {
            "belief_id": belief_id,
            "proposition": proposition,
            "normalized_proposition": normalized,
            "state": state.value,
            "confidence": confidence,
            "support_strength": support,
            "challenge_strength": challenge,
            "evidence_count": new_count,
            "unique_source_count": len(source_ids),
            "unique_family_count": len(families),
            "freshness": freshness,
            "last_run_id": run_id,
            "first_seen_at": first_seen,
            "last_updated_at": now,
            "revision_count": revision_count,
        }
        self.store.put_world_belief(record)
        for item in additions:
            self.store.add_world_belief_evidence(belief_id, item.id, run_id, item.stance.value, now)

        belief = BeliefRecord(
            belief_id=belief_id,
            proposition=proposition,
            normalized_proposition=normalized,
            state=state,
            confidence=confidence,
            support_strength=support,
            challenge_strength=challenge,
            evidence_count=new_count,
            unique_source_count=len(source_ids),
            unique_family_count=len(families),
            freshness=freshness,
            last_run_id=run_id,
            first_seen_at=first_seen,
            last_updated_at=now,
            revision_count=revision_count,
        )
        return BeliefRevision(
            belief=belief,
            added_evidence_ids=tuple(item.id for item in additions),
            previous_state=previous_state,
            previous_confidence=previous_confidence,
            changed=changed,
            reason=reason,
        )

    def list(self, limit: int = 100) -> tuple[BeliefRecord, ...]:
        return tuple(
            BeliefRecord(
                belief_id=row["belief_id"],
                proposition=row["proposition"],
                normalized_proposition=row["normalized_proposition"],
                state=BeliefState(row["state"]),
                confidence=float(row["confidence"]),
                support_strength=float(row["support_strength"]),
                challenge_strength=float(row["challenge_strength"]),
                evidence_count=int(row["evidence_count"]),
                unique_source_count=int(row["unique_source_count"]),
                unique_family_count=int(row["unique_family_count"]),
                freshness=float(row["freshness"]),
                last_run_id=row["last_run_id"],
                first_seen_at=row["first_seen_at"],
                last_updated_at=row["last_updated_at"],
                revision_count=int(row["revision_count"]),
            )
            for row in self.store.list_world_beliefs(limit)
        )

    def get(self, belief_id: str) -> BeliefRecord | None:
        row = self.store.get_world_belief(belief_id)
        if not row:
            return None
        return BeliefRecord(
            belief_id=row["belief_id"],
            proposition=row["proposition"],
            normalized_proposition=row["normalized_proposition"],
            state=BeliefState(row["state"]),
            confidence=float(row["confidence"]),
            support_strength=float(row["support_strength"]),
            challenge_strength=float(row["challenge_strength"]),
            evidence_count=int(row["evidence_count"]),
            unique_source_count=int(row["unique_source_count"]),
            unique_family_count=int(row["unique_family_count"]),
            freshness=float(row["freshness"]),
            last_run_id=row["last_run_id"],
            first_seen_at=row["first_seen_at"],
            last_updated_at=row["last_updated_at"],
            revision_count=int(row["revision_count"]),
        )
