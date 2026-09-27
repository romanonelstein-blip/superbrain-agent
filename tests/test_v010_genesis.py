import unittest

from nexus1000 import (
    Evidence,
    CouncilVerdict,
    NexusOrchestrator,
    ExpertiseGap,
    SpecialistGenesisEngine,
    GenesisBudget,
)
from nexus1000.models import Stance
from nexus1000.councils import SpecialistCouncil
from nexus1000.genesis import ExpertiseGapDetector


def ev(i, stance=Stance.SUPPORT, source=None, family=None, reliability=.9, freshness=.9, relevance=.9, verified=True):
    return Evidence(
        id=f"g{i}",
        claim=f"claim-{i}",
        stance=stance,
        source_id=source or f"gs{i}",
        source_family=family or f"gf{i}",
        reliability=reliability,
        freshness=freshness,
        relevance=relevance,
        verified=verified,
    )


def cv(cid, evidence, unresolved=False, confidence=.9):
    return CouncilVerdict(
        council_id=cid,
        specialty=cid.replace("genesis:", ""),
        evidence=tuple(evidence),
        confidence=confidence,
        unresolved_conflict=unresolved,
        rationale="test",
    )


class TestGapDetector(unittest.TestCase):
    def test_detects_missing_domain(self):
        detector = ExpertiseGapDetector()
        gaps = detector.detect(
            {"legal": ("document_read",), "finance": ("calculation",)},
            ["finance"],
            (),
        )
        self.assertEqual([g.domain for g in gaps], ["legal"])

    def test_does_not_duplicate_existing_specialist(self):
        detector = ExpertiseGapDetector()
        gaps = detector.detect(
            {"legal": ("document_read",)},
            ["LEGAL"],
            (),
        )
        self.assertEqual(gaps, [])

    def test_evidence_hint_increases_priority(self):
        detector = ExpertiseGapDetector()
        gaps = detector.detect(
            {"security": ("document_read",)},
            [],
            (Evidence("x", "security incident", Stance.SUPPORT, "s", "f"),),
        )
        self.assertEqual(gaps[0].priority, .85)


class TestGenesisEngine(unittest.TestCase):
    def test_only_registry_capabilities_are_granted(self):
        engine = SpecialistGenesisEngine({"document_read"})
        bps = engine.create_blueprints([
            ExpertiseGap("legal", "missing", .9, ("document_read", "shell_exec"))
        ])
        self.assertEqual(bps[0].allowed_capabilities, ("document_read",))

    def test_rejects_gap_without_permitted_capability(self):
        engine = SpecialistGenesisEngine({"document_read"})
        bps = engine.create_blueprints([
            ExpertiseGap("network", "missing", .9, ("raw_socket",))
        ])
        self.assertEqual(bps, [])
        self.assertTrue(engine.audit.rejected_gaps)

    def test_low_priority_gap_rejected(self):
        engine = SpecialistGenesisEngine({"document_read"})
        bps = engine.create_blueprints([
            ExpertiseGap("legal", "missing", .2, ("document_read",))
        ])
        self.assertEqual(bps, [])

    def test_creation_budget_is_enforced(self):
        engine = SpecialistGenesisEngine(
            {"document_read"},
            GenesisBudget(max_specialists_per_run=2, min_gap_priority=.1)
        )
        gaps = [
            ExpertiseGap(f"d{i}", "missing", .9, ("document_read",))
            for i in range(5)
        ]
        self.assertEqual(len(engine.create_blueprints(gaps)), 2)

    def test_specialist_evidence_is_bounded(self):
        engine = SpecialistGenesisEngine({"document_read"})
        bp = engine.create_blueprints([
            ExpertiseGap("legal", "missing", .9, ("document_read",))
        ])[0]

        def factory(blueprint):
            def run(question):
                return cv(
                    blueprint.specialist_id,
                    [ev(i, family=f"f{i}") for i in range(20)],
                )
            return run

        specialist = engine.instantiate(bp, factory)
        result = specialist.run("q")
        self.assertEqual(len(result.evidence), bp.max_evidence_items)

    def test_forbidden_authority_is_explicit(self):
        engine = SpecialistGenesisEngine({"document_read"})
        bp = engine.create_blueprints([
            ExpertiseGap("legal", "missing", .9, ("document_read",))
        ])[0]
        self.assertIn("final_judge", bp.forbidden_capabilities)
        self.assertIn("policy_override", bp.forbidden_capabilities)
        self.assertIn("spawn_unbounded", bp.forbidden_capabilities)


class TestGenesisPipeline(unittest.TestCase):
    def _council(self, cid, specialty, evidence):
        return SpecialistCouncil(
            cid,
            specialty,
            lambda q, cid=cid, specialty=specialty, evidence=evidence: CouncilVerdict(
                council_id=cid,
                specialty=specialty,
                evidence=tuple(evidence),
                confidence=.9,
            ),
        )

    def test_missing_specialist_is_created_and_used(self):
        orch = NexusOrchestrator(capability_registry={"document_read", "calculation"})
        councils = [self._council("finance", "finance", [ev(1, family="finance")])]

        def factory(bp):
            def run(question):
                return cv(bp.specialist_id, [ev(2, family=bp.domain)])
            return run

        final = orch.run(
            "q",
            councils,
            required_domains={
                "finance": ("calculation",),
                "legal": ("document_read",),
            },
            genesis_runner_factory=factory,
            dissent_fn=lambda q, e: (),
        )
        stages = [e.stage for e in orch.timeline.events]
        self.assertIn("genesis_gap_detection", stages)
        self.assertIn("genesis_specialist", stages)
        self.assertEqual(len(orch.genesis.audit.blueprints_created), 1)
        self.assertEqual(
            orch.genesis.audit.blueprints_created[0].domain,
            "legal",
        )
        self.assertEqual(final.value, "YES")

    def test_genesis_does_not_bypass_final_judge(self):
        orch = NexusOrchestrator(capability_registry={"document_read"})
        councils = [self._council("base", "base", [ev(1, family="base")])]

        def factory(bp):
            def run(question):
                return cv(bp.specialist_id, [ev(2, family=bp.domain)])
            return run

        final = orch.run(
            "q",
            councils,
            required_domains={"legal": ("document_read",)},
            genesis_runner_factory=factory,
            # No blinded dissent provider: must still be NO.
        )
        self.assertEqual(final.value, "NO")
        self.assertFalse(final.pipeline_passes["blinded_dissent"])

    def test_irrelevant_unpermitted_gap_creates_no_agent(self):
        orch = NexusOrchestrator(capability_registry={"document_read"})
        councils = [self._council("base", "base", [ev(1, family="base")])]

        def factory(bp):
            raise AssertionError("factory should not be called")

        orch.run(
            "q",
            councils,
            required_domains={"network": ("raw_socket",)},
            genesis_runner_factory=factory,
            dissent_fn=lambda q, e: (),
        )
        self.assertEqual(len(orch.genesis.audit.blueprints_created), 0)

    def test_genesis_timeline_is_auditable(self):
        orch = NexusOrchestrator(capability_registry={"document_read"})
        councils = [self._council("base", "base", [ev(1, family="base")])]

        def factory(bp):
            return lambda q: cv(bp.specialist_id, [ev(2, family=bp.domain)])

        orch.run(
            "q",
            councils,
            required_domains={"legal": ("document_read",)},
            genesis_runner_factory=factory,
            dissent_fn=lambda q, e: (),
        )
        msgs = [(e.stage, e.message) for e in orch.timeline.events]
        self.assertTrue(any(s == "genesis_blueprints" and "created=1" in m for s, m in msgs))


if __name__ == "__main__":
    unittest.main()
