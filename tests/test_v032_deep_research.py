import hashlib
import unittest

from nexus1000.deep_research import (
    DeepResearchEngine,
    DeepResearchPolicy,
    assess_knowledge_gaps,
    build_followup_plan,
)
from nexus1000.models import Evidence, Stance
from nexus1000.research import ResearchEngine, RetrievedResearchSource, SearchHit


class ProgressiveSearch:
    name = "progressive-search"

    def search(self, query, limit):
        q = query.casefold()
        if "risks criticism counterevidence limitations" in q:
            return ()
        if "contrary evidence failure risks" in q:
            return (SearchHit("Counter", "https://c.example/c", "counter", self.name, 1, query, Stance.NEUTRAL),)[:limit]
        if "independent analysis study report dataset source" in q:
            return (SearchHit("Independent", "https://d.example/d", "independent", self.name, 1, query, Stance.NEUTRAL),)[:limit]
        return (
            SearchHit("Support A", "https://a.example/a", "a", self.name, 1, query, Stance.NEUTRAL),
            SearchHit("Support B", "https://b.example/b", "b", self.name, 2, query, Stance.NEUTRAL),
        )[:limit]


class DuplicateFollowupSearch(ProgressiveSearch):
    def search(self, query, limit):
        q = query.casefold()
        if "risks criticism counterevidence limitations" in q:
            return ()
        if "contrary evidence failure risks" in q or "independent analysis study report dataset source" in q:
            return (SearchHit("Support A", "https://a.example/a", "dup", self.name, 1, query, Stance.NEUTRAL),)
        return super().search(query, limit)


class Fetcher:
    def fetch(self, hit):
        host = hit.url.split("/")[2]
        return RetrievedResearchSource(
            source_id="source-" + host,
            source_family=host,
            title=hit.title,
            url=hit.url,
            excerpt=f"Retrieved evidence from {host} relevant to the mission.",
            content_hash=hashlib.sha256(hit.url.encode()).hexdigest(),
            retrieved_at="2026-09-20T00:00:00+00:00",
            content_type="text/html",
            query=hit.query,
            stance=hit.stance,
            search_provider=hit.provider,
            rank=hit.rank,
        )


class TestDeepResearchPlanning(unittest.TestCase):
    def test_gap_assessment_detects_support_counterevidence_and_diversity(self):
        policy = DeepResearchPolicy()
        gaps = assess_knowledge_gaps((), policy=policy)
        self.assertEqual([g.code for g in gaps], ["support-depth", "counterevidence", "source-diversity"])

    def test_followup_plan_targets_missing_counterevidence_and_diversity(self):
        policy = DeepResearchPolicy(min_support_sources=0)
        evidence = (
            Evidence("e1", "x", Stance.SUPPORT, "a", "a.example", 0.9, verified=True, citation="x", content_hash="h"),
        )
        gaps = assess_knowledge_gaps(evidence, policy=policy)
        plan = build_followup_plan("Should we launch?", gaps, round_number=2, max_results_per_query=3, max_sources=5)
        self.assertTrue(any(q.stance is Stance.CHALLENGE for q in plan.queries))
        self.assertTrue(any("independent" in q.query.casefold() for q in plan.queries))

    def test_policy_bounds_are_enforced(self):
        with self.assertRaises(ValueError):
            DeepResearchPolicy(max_rounds=99).validate()
        with self.assertRaises(ValueError):
            DeepResearchPolicy(max_total_sources=99).validate()


class TestDeepResearchEngine(unittest.TestCase):
    def test_iterates_until_evidence_sufficiency(self):
        engine = DeepResearchEngine(
            ResearchEngine(ProgressiveSearch(), source_fetcher=Fetcher()),
            policy=DeepResearchPolicy(max_rounds=3, max_total_sources=10),
        )
        outcome = engine.run("Should we launch this product?")
        self.assertEqual(outcome.stop_reason, "evidence_sufficiency_reached")
        self.assertEqual(len(outcome.rounds), 2)
        self.assertGreaterEqual(len(outcome.sources), 3)
        self.assertEqual(outcome.knowledge_gaps, ())
        self.assertTrue(any(e.stance is Stance.CHALLENGE for e in outcome.evidence))

    def test_stops_when_followup_has_low_information_gain(self):
        engine = DeepResearchEngine(
            ResearchEngine(DuplicateFollowupSearch(), source_fetcher=Fetcher()),
            policy=DeepResearchPolicy(max_rounds=4, max_total_sources=10),
        )
        outcome = engine.run("Should we launch this product?")
        self.assertEqual(outcome.stop_reason, "marginal_information_gain_low")
        self.assertEqual(len(outcome.rounds), 2)
        self.assertTrue(outcome.knowledge_gaps)

    def test_respects_round_cap(self):
        engine = DeepResearchEngine(
            ResearchEngine(DuplicateFollowupSearch(), source_fetcher=Fetcher()),
            policy=DeepResearchPolicy(max_rounds=1, max_total_sources=10),
        )
        outcome = engine.run("Should we launch this product?")
        self.assertEqual(outcome.stop_reason, "max_rounds_reached")
        self.assertEqual(len(outcome.rounds), 1)


if __name__ == "__main__":
    unittest.main()
