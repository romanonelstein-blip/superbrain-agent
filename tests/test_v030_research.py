import hashlib
import tempfile
import unittest
from pathlib import Path

from nexus1000.models import Stance
from nexus1000.provider_bridge import ProviderEvidence
from nexus1000.research import (
    ResearchEngine,
    ResearchPolicyError,
    RetrievedResearchSource,
    SafeResearchSourceFetcher,
    SearchHit,
    build_research_plan,
)
from nexus1000.source_retrieval import HttpsResponse


class FakeSearch:
    name = "fake-search"

    def search(self, query, limit):
        if "risks criticism counterevidence limitations" in query:
            return ()
        return (
            SearchHit("Alpha", "https://alpha.example/a", "alpha", self.name, 1, query, Stance.NEUTRAL),
            SearchHit("Beta", "https://beta.example/b", "beta", self.name, 2, query, Stance.NEUTRAL),
            SearchHit("Duplicate", "https://alpha.example/a#fragment", "dup", self.name, 3, query, Stance.NEUTRAL),
        )[:limit]


class FakeFetcher:
    def fetch(self, hit):
        host = hit.url.split("/")[2]
        return RetrievedResearchSource(
            source_id=f"source-{host}",
            source_family=host,
            title=hit.title,
            url=hit.url.split("#", 1)[0],
            excerpt=f"Retrieved evidence from {host} supporting the mission with independently sourced details.",
            content_hash=hashlib.sha256(hit.url.encode()).hexdigest(),
            retrieved_at="2026-09-20T00:00:00+00:00",
            content_type="text/html",
            query=hit.query,
            stance=hit.stance,
            search_provider=hit.provider,
            rank=hit.rank,
        )


class TestResearchPlan(unittest.TestCase):
    def test_plan_contains_primary_and_counterevidence_queries(self):
        plan = build_research_plan("Should we launch this product?")
        self.assertEqual(len(plan.queries), 2)
        self.assertEqual(plan.queries[0].stance, Stance.SUPPORT)
        self.assertEqual(plan.queries[1].stance, Stance.CHALLENGE)
        self.assertIn("counterevidence", plan.queries[1].query)

    def test_plan_bounds_are_enforced(self):
        with self.assertRaises(ValueError):
            build_research_plan("x", max_results_per_query=0)
        with self.assertRaises(ValueError):
            build_research_plan("x", max_sources=99)


class TestResearchEngine(unittest.TestCase):
    def test_engine_deduplicates_urls_and_creates_verified_evidence(self):
        engine = ResearchEngine(FakeSearch(), source_fetcher=FakeFetcher())
        outcome = engine.run(build_research_plan("Should we launch?", max_sources=5))
        self.assertEqual(len(outcome.sources), 2)
        self.assertEqual(len(outcome.evidence), 2)
        self.assertTrue(all(item.verified for item in outcome.evidence))
        self.assertEqual({item.source_family for item in outcome.evidence}, {"alpha.example", "beta.example"})
        self.assertTrue(all(item.citation for item in outcome.evidence))
        self.assertTrue(all(item.content_hash for item in outcome.evidence))

    def test_engine_applies_plan_stance_to_search_hits(self):
        class SearchWithChallenge(FakeSearch):
            def search(self, query, limit):
                if "counterevidence" in query:
                    return (SearchHit("Gamma", "https://gamma.example/g", "risk", self.name, 1, query, Stance.NEUTRAL),)
                return super().search(query, limit)[:1]
        outcome = ResearchEngine(SearchWithChallenge(), source_fetcher=FakeFetcher()).run(
            build_research_plan("Should we launch?", max_sources=3)
        )
        self.assertEqual([e.stance for e in outcome.evidence], [Stance.SUPPORT, Stance.CHALLENGE])


class TestSafeResearchFetcher(unittest.TestCase):
    def test_fetcher_rejects_non_https_before_network(self):
        fetcher = SafeResearchSourceFetcher(dns_resolver=lambda _host: ("93.184.216.34",))
        hit = SearchHit("Bad", "http://example.com/x", "", "fake", 1, "q", Stance.SUPPORT)
        with self.assertRaisesRegex(ResearchPolicyError, "HTTPS"):
            fetcher.fetch(hit)

    def test_fetcher_rejects_ip_literal(self):
        fetcher = SafeResearchSourceFetcher(dns_resolver=lambda _host: ("93.184.216.34",))
        hit = SearchHit("Bad", "https://93.184.216.34/x", "", "fake", 1, "q", Stance.SUPPORT)
        with self.assertRaisesRegex(ResearchPolicyError, "IP literals"):
            fetcher.fetch(hit)

    def test_fetcher_extracts_text_and_hashes_original_bytes(self):
        body = b"<html><head><style>bad</style></head><body><h1>Useful title</h1><script>bad()</script><p>Useful evidence text.</p></body></html>"
        def transport(url, ip, timeout, max_bytes):
            return HttpsResponse(200, {"content-type": "text/html; charset=utf-8"}, body)
        fetcher = SafeResearchSourceFetcher(
            dns_resolver=lambda _host: ("93.184.216.34",),
            transport=transport,
            clock=lambda: "2026-09-20T00:00:00+00:00",
        )
        hit = SearchHit("Title", "https://example.com/a", "", "fake", 1, "q", Stance.SUPPORT)
        source = fetcher.fetch(hit)
        self.assertIn("Useful title", source.excerpt)
        self.assertIn("Useful evidence text", source.excerpt)
        self.assertNotIn("bad()", source.excerpt)
        self.assertEqual(source.content_hash, hashlib.sha256(body).hexdigest())


if __name__ == "__main__":
    unittest.main()
