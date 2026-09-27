from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

from .models import Evidence


_CATEGORY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _normalized(value: str) -> str:
    return " ".join(value.split()).casefold()


def _digest(*parts: str) -> str:
    payload = "\0".join(_normalized(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ReflectionContext:
    run_id: str
    mission: str
    final_value: str
    pipeline_passes: dict[str, bool]
    evidence: tuple[Evidence, ...]

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("reflection run_id cannot be empty")
        if not self.mission.strip():
            raise ValueError("reflection mission cannot be empty")
        if self.final_value not in {"YES", "NO"}:
            raise ValueError("reflection final_value must be YES or NO")
        evidence_ids = [item.id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("reflection evidence ids must be unique")


@dataclass(frozen=True)
class LessonProposal:
    category: str
    lesson: str
    evidence_ids: tuple[str, ...]
    confidence: float
    improvement_candidate: str

    def __post_init__(self) -> None:
        if not _CATEGORY_PATTERN.fullmatch(self.category):
            raise ValueError("lesson category must be a lowercase slug of at most 64 characters")
        if not self.lesson.strip() or len(self.lesson) > 1_000:
            raise ValueError("lesson must contain 1 to 1000 characters")
        if not self.evidence_ids or len(self.evidence_ids) > 50:
            raise ValueError("lesson must reference 1 to 50 evidence items")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("lesson evidence ids must be unique")
        if not math.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("lesson confidence must be finite and in [0, 1]")
        if not self.improvement_candidate.strip() or len(self.improvement_candidate) > 2_000:
            raise ValueError("improvement candidate must contain 1 to 2000 characters")


@dataclass(frozen=True)
class StoredLesson:
    lesson_id: str
    fingerprint: str
    category: str
    lesson: str
    confidence: float
    occurrences: int
    first_seen_at: str
    last_seen_at: str
    latest_run_id: str
    latest_result: str


@dataclass(frozen=True)
class ReflectionRecord:
    run_id: str
    mission: str
    final_value: str
    pipeline_passes: dict[str, bool]
    reflected_at: str


@dataclass(frozen=True)
class LessonEvidence:
    lesson_id: str
    run_id: str
    evidence_id: str
    claim: str
    stance: str
    source_id: str
    source_family: str
    reliability: float
    citation: str
    content_hash: str
    retrieved_at: str | None
    location: str | None
    content_type: str | None
    provider: str | None
    provider_model: str | None
    provider_request_id: str | None
    provider_agent: str | None


@dataclass(frozen=True)
class ImprovementCandidate:
    candidate_id: str
    lesson_id: str
    description: str
    confidence: float
    status: str
    occurrences: int
    first_proposed_at: str
    last_proposed_at: str
    latest_run_id: str


@dataclass(frozen=True)
class LearningOutcome:
    lessons: tuple[StoredLesson, ...]
    improvement_candidates: tuple[ImprovementCandidate, ...]


class SQLiteLearningStore:
    """Dedicated append-oriented store for evidence-backed lessons and proposals."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._initialize()

    def _initialize(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS learning_lessons (
                lesson_id TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL UNIQUE,
                category TEXT NOT NULL,
                lesson TEXT NOT NULL,
                confidence REAL NOT NULL CHECK(confidence >= 0.0 AND confidence <= 1.0),
                occurrences INTEGER NOT NULL CHECK(occurrences >= 0),
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                latest_run_id TEXT NOT NULL,
                latest_result TEXT NOT NULL CHECK(latest_result IN ('YES', 'NO'))
            );

            CREATE TABLE IF NOT EXISTS learning_reflection_runs (
                run_id TEXT PRIMARY KEY,
                mission TEXT NOT NULL,
                final_result TEXT NOT NULL CHECK(final_result IN ('YES', 'NO')),
                pipeline_passes_json TEXT NOT NULL,
                reflected_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS learning_lesson_runs (
                lesson_id TEXT NOT NULL REFERENCES learning_lessons(lesson_id) ON DELETE CASCADE,
                run_id TEXT NOT NULL REFERENCES learning_reflection_runs(run_id) ON DELETE CASCADE,
                final_result TEXT NOT NULL CHECK(final_result IN ('YES', 'NO')),
                observed_at TEXT NOT NULL,
                PRIMARY KEY (lesson_id, run_id)
            );

            CREATE TABLE IF NOT EXISTS learning_lesson_evidence (
                lesson_id TEXT NOT NULL REFERENCES learning_lessons(lesson_id) ON DELETE CASCADE,
                run_id TEXT NOT NULL REFERENCES learning_reflection_runs(run_id) ON DELETE CASCADE,
                evidence_id TEXT NOT NULL,
                claim TEXT NOT NULL,
                stance TEXT NOT NULL,
                source_id TEXT NOT NULL,
                source_family TEXT NOT NULL,
                reliability REAL NOT NULL CHECK(reliability >= 0.0 AND reliability <= 1.0),
                citation TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                retrieved_at TEXT,
                location TEXT,
                content_type TEXT,
                provider TEXT,
                provider_model TEXT,
                provider_request_id TEXT,
                provider_agent TEXT,
                PRIMARY KEY (lesson_id, run_id, evidence_id)
            );

            CREATE TABLE IF NOT EXISTS learning_improvement_candidates (
                candidate_id TEXT PRIMARY KEY,
                lesson_id TEXT NOT NULL REFERENCES learning_lessons(lesson_id) ON DELETE CASCADE,
                description TEXT NOT NULL,
                confidence REAL NOT NULL CHECK(confidence >= 0.0 AND confidence <= 1.0),
                status TEXT NOT NULL CHECK(status = 'PROPOSED'),
                occurrences INTEGER NOT NULL CHECK(occurrences >= 0),
                first_proposed_at TEXT NOT NULL,
                last_proposed_at TEXT NOT NULL,
                latest_run_id TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS learning_improvement_candidate_runs (
                candidate_id TEXT NOT NULL
                    REFERENCES learning_improvement_candidates(candidate_id) ON DELETE CASCADE,
                run_id TEXT NOT NULL REFERENCES learning_reflection_runs(run_id) ON DELETE CASCADE,
                proposed_at TEXT NOT NULL,
                PRIMARY KEY (candidate_id, run_id)
            );
            """
        )
        self.conn.commit()

    def record_reflection(self, context: ReflectionContext, reflected_at: str) -> ReflectionRecord:
        pipeline_json = json.dumps(context.pipeline_passes, sort_keys=True, separators=(",", ":"))
        with self.conn:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO learning_reflection_runs (
                    run_id, mission, final_result, pipeline_passes_json, reflected_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    context.run_id,
                    context.mission,
                    context.final_value,
                    pipeline_json,
                    reflected_at,
                ),
            )
        row = self.conn.execute(
            "SELECT * FROM learning_reflection_runs WHERE run_id = ?", (context.run_id,)
        ).fetchone()
        if row is None:
            raise RuntimeError("learning store failed to read its reflection record")
        if (
            row["mission"] != context.mission
            or row["final_result"] != context.final_value
            or row["pipeline_passes_json"] != pipeline_json
        ):
            raise ValueError(f"conflicting reflection context for run: {context.run_id}")
        return ReflectionRecord(
            row["run_id"],
            row["mission"],
            row["final_result"],
            json.loads(row["pipeline_passes_json"]),
            row["reflected_at"],
        )

    @staticmethod
    def _lesson_from_row(row: sqlite3.Row) -> StoredLesson:
        return StoredLesson(
            row["lesson_id"],
            row["fingerprint"],
            row["category"],
            row["lesson"],
            row["confidence"],
            row["occurrences"],
            row["first_seen_at"],
            row["last_seen_at"],
            row["latest_run_id"],
            row["latest_result"],
        )

    @staticmethod
    def _candidate_from_row(row: sqlite3.Row) -> ImprovementCandidate:
        return ImprovementCandidate(
            row["candidate_id"],
            row["lesson_id"],
            row["description"],
            row["confidence"],
            row["status"],
            row["occurrences"],
            row["first_proposed_at"],
            row["last_proposed_at"],
            row["latest_run_id"],
        )

    def record(
        self,
        context: ReflectionContext,
        proposal: LessonProposal,
        referenced_evidence: tuple[Evidence, ...],
        observed_at: str,
    ) -> tuple[StoredLesson, ImprovementCandidate]:
        fingerprint = _digest(proposal.category, proposal.lesson)
        lesson_id = f"lesson-{fingerprint[:24]}"
        candidate_fingerprint = _digest(lesson_id, proposal.improvement_candidate)
        candidate_id = f"candidate-{candidate_fingerprint[:24]}"

        with self.conn:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO learning_lessons (
                    lesson_id, fingerprint, category, lesson, confidence, occurrences,
                    first_seen_at, last_seen_at, latest_run_id, latest_result
                ) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
                """,
                (
                    lesson_id,
                    fingerprint,
                    proposal.category,
                    proposal.lesson.strip(),
                    proposal.confidence,
                    observed_at,
                    observed_at,
                    context.run_id,
                    context.final_value,
                ),
            )
            lesson_run = self.conn.execute(
                """
                INSERT OR IGNORE INTO learning_lesson_runs (
                    lesson_id, run_id, final_result, observed_at
                ) VALUES (?, ?, ?, ?)
                """,
                (lesson_id, context.run_id, context.final_value, observed_at),
            )
            occurrence_delta = 1 if lesson_run.rowcount == 1 else 0
            self.conn.execute(
                """
                UPDATE learning_lessons
                SET confidence = MAX(confidence, ?),
                    occurrences = occurrences + ?,
                    last_seen_at = ?,
                    latest_run_id = ?,
                    latest_result = ?
                WHERE lesson_id = ?
                """,
                (
                    proposal.confidence,
                    occurrence_delta,
                    observed_at,
                    context.run_id,
                    context.final_value,
                    lesson_id,
                ),
            )
            for item in referenced_evidence:
                self.conn.execute(
                    """
                    INSERT OR IGNORE INTO learning_lesson_evidence (
                        lesson_id, run_id, evidence_id, claim, stance,
                        source_id, source_family, reliability, citation, content_hash,
                        retrieved_at, location, content_type, provider, provider_model,
                        provider_request_id, provider_agent
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        lesson_id,
                        context.run_id,
                        item.id,
                        item.claim,
                        item.stance.value,
                        item.source_id,
                        item.source_family,
                        item.reliability,
                        item.citation,
                        item.content_hash,
                        item.retrieved_at,
                        item.location,
                        item.content_type,
                        item.provider,
                        item.provider_model,
                        item.provider_request_id,
                        item.provider_agent,
                    ),
                )

            self.conn.execute(
                """
                INSERT OR IGNORE INTO learning_improvement_candidates (
                    candidate_id, lesson_id, description, confidence, status,
                    occurrences, first_proposed_at, last_proposed_at, latest_run_id
                ) VALUES (?, ?, ?, ?, 'PROPOSED', 0, ?, ?, ?)
                """,
                (
                    candidate_id,
                    lesson_id,
                    proposal.improvement_candidate.strip(),
                    proposal.confidence,
                    observed_at,
                    observed_at,
                    context.run_id,
                ),
            )
            candidate_run = self.conn.execute(
                """
                INSERT OR IGNORE INTO learning_improvement_candidate_runs (
                    candidate_id, run_id, proposed_at
                ) VALUES (?, ?, ?)
                """,
                (candidate_id, context.run_id, observed_at),
            )
            candidate_delta = 1 if candidate_run.rowcount == 1 else 0
            self.conn.execute(
                """
                UPDATE learning_improvement_candidates
                SET confidence = MAX(confidence, ?),
                    occurrences = occurrences + ?,
                    last_proposed_at = ?,
                    latest_run_id = ?
                WHERE candidate_id = ?
                """,
                (
                    proposal.confidence,
                    candidate_delta,
                    observed_at,
                    context.run_id,
                    candidate_id,
                ),
            )

        lesson_row = self.conn.execute(
            "SELECT * FROM learning_lessons WHERE lesson_id = ?", (lesson_id,)
        ).fetchone()
        candidate_row = self.conn.execute(
            "SELECT * FROM learning_improvement_candidates WHERE candidate_id = ?",
            (candidate_id,),
        ).fetchone()
        if lesson_row is None or candidate_row is None:
            raise RuntimeError("learning store failed to read its committed records")
        return self._lesson_from_row(lesson_row), self._candidate_from_row(candidate_row)

    def list_lessons(self) -> tuple[StoredLesson, ...]:
        rows = self.conn.execute(
            "SELECT * FROM learning_lessons ORDER BY first_seen_at, lesson_id"
        ).fetchall()
        return tuple(self._lesson_from_row(row) for row in rows)

    def list_reflections(self) -> tuple[ReflectionRecord, ...]:
        rows = self.conn.execute(
            "SELECT * FROM learning_reflection_runs ORDER BY reflected_at, run_id"
        ).fetchall()
        return tuple(
            ReflectionRecord(
                row["run_id"],
                row["mission"],
                row["final_result"],
                json.loads(row["pipeline_passes_json"]),
                row["reflected_at"],
            )
            for row in rows
        )

    def list_lesson_evidence(self, lesson_id: str) -> tuple[LessonEvidence, ...]:
        rows = self.conn.execute(
            """
            SELECT * FROM learning_lesson_evidence
            WHERE lesson_id = ?
            ORDER BY run_id, evidence_id
            """,
            (lesson_id,),
        ).fetchall()
        return tuple(
            LessonEvidence(
                row["lesson_id"],
                row["run_id"],
                row["evidence_id"],
                row["claim"],
                row["stance"],
                row["source_id"],
                row["source_family"],
                row["reliability"],
                row["citation"],
                row["content_hash"],
                row["retrieved_at"],
                row["location"],
                row["content_type"],
                row["provider"],
                row["provider_model"],
                row["provider_request_id"],
                row["provider_agent"],
            )
            for row in rows
        )

    def list_improvement_candidates(self) -> tuple[ImprovementCandidate, ...]:
        rows = self.conn.execute(
            """
            SELECT * FROM learning_improvement_candidates
            ORDER BY first_proposed_at, candidate_id
            """
        ).fetchall()
        return tuple(self._candidate_from_row(row) for row in rows)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> SQLiteLearningStore:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()


class ControlledLearningLoop:
    """Validates reflector output and stores proposals without applying them."""

    def __init__(
        self,
        store: SQLiteLearningStore,
        reflector: Callable[[ReflectionContext], Sequence[LessonProposal]],
        *,
        max_lessons_per_run: int = 20,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if max_lessons_per_run < 1 or max_lessons_per_run > 100:
            raise ValueError("max_lessons_per_run must be in [1, 100]")
        self.store = store
        self.reflector = reflector
        self.max_lessons_per_run = max_lessons_per_run
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _validate_proposal(
        proposal: LessonProposal,
        evidence_by_id: dict[str, Evidence],
    ) -> tuple[Evidence, ...]:
        referenced: list[Evidence] = []
        for evidence_id in proposal.evidence_ids:
            item = evidence_by_id.get(evidence_id)
            if item is None:
                raise ValueError(f"lesson references unknown evidence: {evidence_id}")
            if not item.verified:
                raise ValueError(f"lesson references unverified evidence: {evidence_id}")
            if not item.citation or not item.content_hash:
                raise ValueError(f"lesson evidence lacks provenance: {evidence_id}")
            referenced.append(item)
        evidence_bound = min(item.reliability for item in referenced)
        if proposal.confidence > evidence_bound:
            raise ValueError(
                "lesson confidence exceeds the least reliable referenced evidence "
                f"({proposal.confidence} > {evidence_bound})"
            )
        return tuple(referenced)

    def run(self, context: ReflectionContext) -> LearningOutcome:
        proposals = tuple(self.reflector(context))
        if len(proposals) > self.max_lessons_per_run:
            raise ValueError(
                f"reflector returned {len(proposals)} lessons; limit is {self.max_lessons_per_run}"
            )
        if not all(isinstance(item, LessonProposal) for item in proposals):
            raise TypeError("reflector must return only LessonProposal values")

        evidence_by_id = {item.id: item for item in context.evidence}
        observed_at = self.clock().astimezone(timezone.utc).isoformat()
        validated = tuple(
            (proposal, self._validate_proposal(proposal, evidence_by_id))
            for proposal in proposals
        )
        self.store.record_reflection(context, observed_at)
        lessons: dict[str, StoredLesson] = {}
        candidates: dict[str, ImprovementCandidate] = {}
        for proposal, referenced in validated:
            lesson, candidate = self.store.record(context, proposal, referenced, observed_at)
            lessons[lesson.lesson_id] = lesson
            candidates[candidate.candidate_id] = candidate
        return LearningOutcome(tuple(lessons.values()), tuple(candidates.values()))
