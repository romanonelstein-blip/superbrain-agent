import unittest

from nexus1000 import Evidence, CouncilVerdict, NexusOrchestrator
from nexus1000.models import Stance
from nexus1000.councils import SpecialistCouncil
from nexus1000.evidence_graph import EvidenceGraph
from nexus1000.neis import NEIS, NEISConfig
from nexus1000.grand_council import GrandCouncil, GrandCouncilConfig, EscalationBudget
from nexus1000.dissent import BlindedDissent
from nexus1000.verifier import Verifier


def ev(i, stance=Stance.SUPPORT, source=None, family=None, reliability=.9, freshness=.9, relevance=.9, verified=True):
    return Evidence(
        id=f"e{i}",
        claim=f"claim-{i}",
        stance=stance,
        source_id=source or f"s{i}",
        source_family=family or f"f{i}",
        reliability=reliability,
        freshness=freshness,
        relevance=relevance,
        verified=verified,
    )


def cv(cid, evidence, unresolved=False, confidence=.9):
    return CouncilVerdict(
        council_id=cid,
        specialty=cid,
        evidence=tuple(evidence),
        confidence=confidence,
        unresolved_conflict=unresolved,
    )


class TestEvidenceGraph(unittest.TestCase):
    def test_independence_unique_sources(self):
        g = EvidenceGraph.from_evidence([ev(1), ev(2)])
        self.assertEqual(g.independence_score(), 1.0)

    def test_independence_duplicate_source(self):
        g = EvidenceGraph.from_evidence([ev(1, source="x"), ev(2, source="x")])
        self.assertEqual(g.independence_score(), 0.5)

    def test_family_diversity(self):
        g = EvidenceGraph.from_evidence([ev(1, family="a"), ev(2, family="a"), ev(3, family="b")])
        self.assertAlmostEqual(g.family_diversity_score(), 2/3)

    def test_strength_uses_quality_not_votes(self):
        g = EvidenceGraph.from_evidence([
            ev(1, reliability=1, freshness=1, relevance=1),
            ev(2, reliability=.1, freshness=.1, relevance=.1),
        ])
        self.assertAlmostEqual(g.stance_strength(Stance.SUPPORT), 1.001)

    def test_conflict_ratio(self):
        g = EvidenceGraph.from_evidence([
            ev(1, Stance.SUPPORT, reliability=1, freshness=1, relevance=1),
            ev(2, Stance.CHALLENGE, reliability=1, freshness=1, relevance=1),
        ])
        self.assertEqual(g.conflict_ratio(), 1.0)


class TestNEIS(unittest.TestCase):
    def test_no_evidence_fails(self):
        self.assertFalse(NEIS().evaluate(()).passed)

    def test_two_families_pass(self):
        self.assertTrue(NEIS().evaluate((ev(1, family="a"), ev(2, family="b"))).passed)

    def test_single_family_fails(self):
        self.assertFalse(NEIS().evaluate((ev(1, family="a"), ev(2, family="a"))).passed)

    def test_dominant_family_quarantined(self):
        n = NEIS(NEISConfig(max_family_share=.6, min_source_families=2))
        evidence = tuple([ev(i, family="same") for i in range(1, 5)] + [ev(5, family="other")])
        r = n.evaluate(evidence)
        self.assertTrue(len(r.quarantined_ids) >= 1)


class TestGrandCouncil(unittest.TestCase):
    def setUp(self):
        self.gc = GrandCouncil(
            config=GrandCouncilConfig(
                min_support_strength=1.0,
                min_independence=.5,
                min_family_diversity=.4,
                min_freshness=.5,
                min_reliability=.5,
                max_conflict_ratio=.45,
            ),
            budget=EscalationBudget(max_rounds=2, max_extra_councils=3, min_novel_evidence_ratio=.2),
        )

    def test_good_evidence_provisional_yes(self):
        r = self.gc.adjudicate([
            cv("a", [ev(1, family="fa")]),
            cv("b", [ev(2, family="fb")]),
        ])
        self.assertTrue(r.provisional_yes)

    def test_unresolved_council_conflict_blocks(self):
        r = self.gc.adjudicate([
            cv("a", [ev(1, family="fa")], unresolved=True),
            cv("b", [ev(2, family="fb")]),
        ])
        self.assertFalse(r.provisional_yes)
        self.assertTrue(r.unresolved_conflict)

    def test_material_counterevidence_blocks(self):
        r = self.gc.adjudicate([
            cv("a", [ev(1, Stance.SUPPORT, family="fa")]),
            cv("b", [ev(2, Stance.CHALLENGE, family="fb")]),
        ])
        self.assertFalse(r.provisional_yes)

    def test_low_freshness_blocks(self):
        r = self.gc.adjudicate([
            cv("a", [ev(1, family="fa", freshness=.1)]),
            cv("b", [ev(2, family="fb", freshness=.1)]),
        ])
        self.assertFalse(r.provisional_yes)

    def test_escalation_can_resolve_insufficient_evidence(self):
        base = [cv("a", [ev(1, family="fa")])]
        def escalate(round_no, current):
            return [cv(f"x{round_no}", [ev(10 + round_no, family=f"fx{round_no}")])]
        r = self.gc.adjudicate(base, escalate_fn=escalate)
        self.assertTrue(r.escalated)
        self.assertTrue(r.provisional_yes)

    def test_escalation_budget_stops(self):
        base = [cv("a", [ev(1, family="fa", reliability=.2)])]
        def escalate(round_no, current):
            return [cv(f"x{round_no}", [ev(10 + round_no, family=f"fx{round_no}", reliability=.2)])]
        r = self.gc.adjudicate(base, escalate_fn=escalate)
        self.assertTrue(r.escalated)
        self.assertLessEqual(r.escalation_rounds, 2)

    def test_no_new_council_stops(self):
        r = self.gc.adjudicate([cv("a", [ev(1, family="fa")])], escalate_fn=lambda *_: [])
        self.assertIn("no new councils", r.stop_reason)

    def test_novelty_stop(self):
        base = [cv("a", [ev(1, family="fa")])]
        def escalate(round_no, current):
            return [cv("dup", [ev(1, family="fa")])]
        r = self.gc.adjudicate(base, escalate_fn=escalate)
        self.assertIn("novelty below threshold", r.stop_reason)


class TestDissentVerifier(unittest.TestCase):
    def test_dissent_without_provider_fails(self):
        r = BlindedDissent().evaluate("q", (ev(1),), None)
        self.assertFalse(r.passed)

    def test_strong_counterevidence_fails_dissent(self):
        r = BlindedDissent().evaluate(
            "q",
            (ev(1),),
            lambda q, e: (ev(2, Stance.CHALLENGE, family="z"),),
        )
        self.assertFalse(r.passed)

    def test_no_material_counterevidence_passes_dissent(self):
        r = BlindedDissent().evaluate(
            "q",
            (ev(1),),
            lambda q, e: (ev(2, Stance.CHALLENGE, family="z", reliability=.1),),
        )
        self.assertTrue(r.passed)

    def test_verifier_blocks_unresolved_conflict(self):
        self.assertFalse(Verifier().verify((ev(1),), True).passed)

    def test_verifier_blocks_unverified(self):
        self.assertFalse(Verifier().verify((ev(1, verified=False),), False).passed)


class TestFullPipeline(unittest.TestCase):
    def _council(self, cid, e):
        return SpecialistCouncil(cid, cid, lambda q, cid=cid, e=e: cv(cid, e))

    def test_full_yes_requires_all_gates(self):
        orch = NexusOrchestrator()
        councils = [
            self._council("a", [ev(1, family="fa")]),
            self._council("b", [ev(2, family="fb")]),
        ]
        final = orch.run(
            "question",
            councils,
            dissent_fn=lambda q, e: (),
        )
        self.assertEqual(final.value, "YES")
        self.assertTrue(all(final.pipeline_passes.values()))

    def test_no_dissent_provider_means_no(self):
        orch = NexusOrchestrator()
        councils = [
            self._council("a", [ev(1, family="fa")]),
            self._council("b", [ev(2, family="fb")]),
        ]
        final = orch.run("question", councils)
        self.assertEqual(final.value, "NO")
        self.assertFalse(final.pipeline_passes["blinded_dissent"])

    def test_999_like_same_family_cannot_force_yes(self):
        orch = NexusOrchestrator()
        many = [ev(i, family="same", source=f"s{i}") for i in range(1, 51)]
        councils = [self._council("mass", many)]
        final = orch.run("question", councils, dissent_fn=lambda q, e: ())
        self.assertEqual(final.value, "NO")
        self.assertFalse(final.pipeline_passes["neis"])

    def test_timeline_contains_all_core_stages(self):
        orch = NexusOrchestrator()
        councils = [
            self._council("a", [ev(1, family="fa")]),
            self._council("b", [ev(2, family="fb")]),
        ]
        orch.run("question", councils, dissent_fn=lambda q, e: ())
        stages = [e.stage for e in orch.timeline.events]
        for required in ["swarm", "councils", "grand_council", "neis", "blinded_dissent", "verifier", "final_judge"]:
            self.assertIn(required, stages)


if __name__ == "__main__":
    unittest.main()
