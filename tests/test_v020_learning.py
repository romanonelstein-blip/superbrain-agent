import tempfile
import unittest
from pathlib import Path

from nexus1000 import Evidence, NexusOrchestrator, SQLiteStateStore, Stance
from nexus1000.learning import (
    ControlledLearningLoop,
    LessonProposal,
    ReflectionContext,
    SQLiteLearningStore,
)


def evidence(
    evidence_id: str,
    *,
    family: str,
    reliability: float = 0.9,
    verified: bool = True,
) -> Evidence:
    return Evidence(
        id=evidence_id,
        claim=f"claim-{evidence_id}",
        stance=Stance.SUPPORT,
        source_id=f"source-{evidence_id}",
        source_family=family,
        reliability=reliability,
        freshness=0.9,
        relevance=0.9,
        verified=verified,
        citation=f"document://{evidence_id}#quote",
        content_hash=f"sha256:{evidence_id}",
    )


def context(run_id: str = "run-1") -> ReflectionContext:
    return ReflectionContext(
        run_id=run_id,
        mission="Should the evidence-backed launch proceed?",
        final_value="YES",
        pipeline_passes={"neis": True, "blinded_dissent": True, "verifier": True},
        evidence=(
            evidence("e1", family="research"),
            evidence("e2", family="commerce"),
        ),
    )


def proposal() -> LessonProposal:
    return LessonProposal(
        category="evidence-quality",
        lesson="Independent source families reduced single-source risk.",
        evidence_ids=("e1", "e2"),
        confidence=0.85,
        improvement_candidate="Preserve dual-family evidence collection for launch decisions.",
    )


class TestControlledLearningLoop(unittest.TestCase):
    def test_stores_evidence_bound_lesson_and_proposed_candidate(self):
        with tempfile.TemporaryDirectory() as temporary:
            with SQLiteLearningStore(Path(temporary) / "learning.db") as store:
                outcome = ControlledLearningLoop(store, lambda _context: (proposal(),)).run(context())

                self.assertEqual(len(outcome.lessons), 1)
                self.assertEqual(outcome.lessons[0].confidence, 0.85)
                self.assertEqual(outcome.lessons[0].occurrences, 1)
                self.assertEqual(len(store.list_lesson_evidence(outcome.lessons[0].lesson_id)), 2)
                self.assertEqual(outcome.improvement_candidates[0].status, "PROPOSED")
                self.assertEqual(store.list_reflections()[0].mission, context().mission)

    def test_rejects_unknown_or_unverified_evidence(self):
        cases = (
            LessonProposal("quality", "Unknown reference.", ("missing",), 0.5, "Review inputs."),
            LessonProposal("quality", "Unverified reference.", ("e3",), 0.5, "Review inputs."),
        )
        invalid_context = ReflectionContext(
            run_id="invalid",
            mission="mission",
            final_value="NO",
            pipeline_passes={"verifier": False},
            evidence=(evidence("e3", family="unknown", verified=False),),
        )
        with tempfile.TemporaryDirectory() as temporary:
            for index, item in enumerate(cases):
                with self.subTest(index=index):
                    with SQLiteLearningStore(Path(temporary) / f"invalid-{index}.db") as store:
                        loop = ControlledLearningLoop(store, lambda _context, item=item: (item,))
                        with self.assertRaises(ValueError):
                            loop.run(invalid_context)
                        self.assertEqual(store.list_lessons(), ())

    def test_rejects_confidence_above_evidence_reliability(self):
        overconfident = LessonProposal(
            "quality",
            "This confidence is not evidence bounded.",
            ("e1",),
            0.95,
            "Review calibration.",
        )
        low_reliability_context = ReflectionContext(
            run_id="confidence",
            mission="mission",
            final_value="YES",
            pipeline_passes={"verifier": True},
            evidence=(evidence("e1", family="research", reliability=0.7),),
        )
        with tempfile.TemporaryDirectory() as temporary:
            with SQLiteLearningStore(Path(temporary) / "learning.db") as store:
                with self.assertRaisesRegex(ValueError, "confidence"):
                    ControlledLearningLoop(store, lambda _context: (overconfident,)).run(
                        low_reliability_context
                    )

    def test_deduplicates_across_runs_and_within_one_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "learning.db"
            with SQLiteLearningStore(database) as store:
                loop = ControlledLearningLoop(store, lambda _context: (proposal(), proposal()))
                first = loop.run(context("run-1"))
                normalized_duplicate = LessonProposal(
                    "evidence-quality",
                    "  INDEPENDENT source families reduced single-source risk.  ",
                    ("e1", "e2"),
                    0.85,
                    "PRESERVE dual-family evidence collection for launch decisions.",
                )
                second = ControlledLearningLoop(
                    store,
                    lambda _context: (normalized_duplicate,),
                ).run(context("run-2"))

                lessons = store.list_lessons()
                self.assertEqual(len(lessons), 1)
                self.assertEqual(lessons[0].occurrences, 2)
                self.assertEqual(first.lessons[0].lesson_id, second.lessons[0].lesson_id)
                self.assertEqual(len(store.list_improvement_candidates()), 1)

    def test_learning_store_survives_reopen(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "learning.db"
            with SQLiteLearningStore(database) as store:
                ControlledLearningLoop(store, lambda _context: (proposal(),)).run(context())
            with SQLiteLearningStore(database) as reopened:
                self.assertEqual(reopened.list_lessons()[0].occurrences, 1)
                self.assertEqual(
                    reopened.list_improvement_candidates()[0].status,
                    "PROPOSED",
                )

    def test_reflection_requires_source_provenance(self):
        missing_provenance = Evidence(
            id="e1",
            claim="claim",
            stance=Stance.SUPPORT,
            source_id="source",
            source_family="family",
            reliability=0.9,
            verified=True,
        )
        invalid_context = ReflectionContext(
            run_id="missing-provenance",
            mission="mission",
            final_value="YES",
            pipeline_passes={"verifier": True},
            evidence=(missing_provenance,),
        )
        with tempfile.TemporaryDirectory() as temporary:
            with SQLiteLearningStore(Path(temporary) / "learning.db") as store:
                loop = ControlledLearningLoop(
                    store,
                    lambda _context: (
                        LessonProposal("quality", "lesson", ("e1",), 0.8, "candidate"),
                    ),
                )
                with self.assertRaisesRegex(ValueError, "provenance"):
                    loop.run(invalid_context)

    def test_orchestrator_emits_reflection_audit_and_persists_learning(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with SQLiteStateStore(root / "state.db") as state_store, SQLiteLearningStore(
                root / "learning.db"
            ) as learning_store:
                loop = ControlledLearningLoop(learning_store, lambda _context: (proposal(),))
                orchestrator = NexusOrchestrator(
                    state_store=state_store,
                    learning_loop=loop,
                )
                final = orchestrator.run_evidence_mission(
                    "Should the evidence-backed launch proceed?",
                    context().evidence,
                    dissent_fn=lambda _question, _evidence: (),
                    run_id="orchestrated-learning",
                )

                audit_stages = [stage for stage, _message in state_store.list_run_audit(
                    "orchestrated-learning"
                )]
                self.assertEqual(final.value, "YES")
                self.assertEqual(learning_store.list_lessons()[0].latest_run_id, "orchestrated-learning")
                self.assertIn("reflection", audit_stages)
                self.assertIn("learning_store", audit_stages)
                self.assertIn("improvement_candidates", audit_stages)

    def test_orchestrator_verifier_rejection_skips_reflection(self):
        calls = []
        rejected_evidence = (
            evidence("e1", family="research", verified=False),
            evidence("e2", family="commerce", verified=False),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with SQLiteStateStore(root / "state.db") as state_store, SQLiteLearningStore(
                root / "learning.db"
            ) as learning_store:
                loop = ControlledLearningLoop(
                    learning_store,
                    lambda reflection_context: calls.append(reflection_context) or (proposal(),),
                )
                orchestrator = NexusOrchestrator(
                    state_store=state_store,
                    learning_loop=loop,
                )
                final = orchestrator.run_evidence_mission(
                    "Should unverified evidence be learned?",
                    rejected_evidence,
                    dissent_fn=lambda _question, _evidence: (),
                    run_id="verifier-rejection",
                )

                audit = state_store.list_run_audit("verifier-rejection")
                self.assertFalse(final.pipeline_passes["verifier"])
                self.assertEqual(calls, [])
                self.assertEqual(learning_store.list_reflections(), ())
                self.assertEqual(learning_store.list_lessons(), ())
                self.assertIn(
                    ("reflection", "skipped: verifier gate did not pass"),
                    audit,
                )

    def test_reflection_failure_is_explicit_in_run_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with SQLiteStateStore(root / "state.db") as state_store, SQLiteLearningStore(
                root / "learning.db"
            ) as learning_store:
                invalid = LessonProposal(
                    "quality",
                    "Unknown evidence must fail explicitly.",
                    ("missing",),
                    0.5,
                    "Review evidence mapping.",
                )
                orchestrator = NexusOrchestrator(
                    state_store=state_store,
                    learning_loop=ControlledLearningLoop(
                        learning_store,
                        lambda _context: (invalid,),
                    ),
                )
                with self.assertRaisesRegex(ValueError, "unknown evidence"):
                    orchestrator.run_evidence_mission(
                        "Should the launch proceed?",
                        context().evidence,
                        dissent_fn=lambda _question, _evidence: (),
                        run_id="reflection-failure",
                    )

                run = state_store.get_run("reflection-failure")
                self.assertIsNotNone(run)
                self.assertEqual(run.status, "reflection_failed")
                self.assertEqual(learning_store.list_lessons(), ())


if __name__ == "__main__":
    unittest.main()
