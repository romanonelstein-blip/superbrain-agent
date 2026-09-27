import json
import tempfile
import unittest
from pathlib import Path

from nexus1000 import (
    NexusOrchestrator,
    ProviderEvidence,
    RetrievedSource,
    SourceBackedClaim,
    SourceEvidenceEnricher,
    SQLiteStateStore,
    Stance,
    TypeScriptProviderBridge,
)


class TestProviderIntegration(unittest.TestCase):
    def test_provider_provenance_reaches_nexus_and_unverified_claims_are_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            with SQLiteStateStore(Path(td) / "n.db") as store:
                orchestrator = NexusOrchestrator(state_store=store)
                final = orchestrator.run_provider_mission(
                    "Should we launch?",
                    (
                        ProviderEvidence("e1", "Demand exists", "openai", "model-a", "req-1", "research"),
                        ProviderEvidence("e2", "Margins work", "anthropic", "model-b", "req-2", "finance"),
                    ),
                    dissent_fn=lambda _question, _evidence: (),
                    run_id="run-1",
                )

                self.assertEqual(final.value, "NO")
                self.assertFalse(final.pipeline_passes["verifier"])
                persisted = store.list_evidence("run-1")
                self.assertEqual([item.source_id for item in persisted], ["req-1", "req-2"])
                self.assertEqual([item.source_family for item in persisted], ["openai", "anthropic"])
                self.assertEqual(store.get_run("run-1").final_value, "NO")
                self.assertIn("final_judge", [stage for stage, _detail in store.list_run_audit("run-1")])

    def test_empty_provider_batch_is_explicit_failure(self):
        with self.assertRaisesRegex(ValueError, "no evidence"):
            NexusOrchestrator().run_provider_mission("question", ())

    def test_bridge_rejects_provider_process_failure(self):
        with tempfile.TemporaryDirectory() as td:
            bridge = TypeScriptProviderBridge(
                td,
                command=("python", "-S", "-c", "import sys; sys.stderr.write('offline'); sys.exit(7)"),
            )
            with self.assertRaisesRegex(RuntimeError, "offline"):
                bridge.run("question")

    def test_bridge_parses_structured_provider_evidence(self):
        payload = json.dumps({
            "evidence": [{
                "evidence_id": "e1", "claim": "claim", "provider": "openai",
                "model": "m", "request_id": "req", "agent": "research",
                "attempts": 2, "latency_ms": 7,
                "verified": False, "reliability": 0.5, "freshness": 1.0, "relevance": 1.0,
            }]
        })
        with tempfile.TemporaryDirectory() as td:
            bridge = TypeScriptProviderBridge(td, command=("python", "-S", "-c", f"print({payload!r})"))
            evidence = bridge.run("question")
            self.assertEqual(evidence[0].request_id, "req")
            self.assertEqual(evidence[0].attempts, 2)
            self.assertEqual(evidence[0].latency_ms, 7)

    def test_provider_cannot_mark_its_own_claim_verified(self):
        final = NexusOrchestrator().run_provider_mission(
            "question",
            (
                ProviderEvidence("e1", "claim one", "openai", "m", verified=True),
                ProviderEvidence("e2", "claim two", "anthropic", "m", verified=True),
            ),
            dissent_fn=lambda _question, _evidence: (),
        )
        self.assertEqual(final.value, "NO")
        self.assertFalse(final.pipeline_passes["verifier"])

    def test_independently_supported_sources_can_reach_yes(self):
        provider_claim = ProviderEvidence("claim-1", "The launch has validated demand", "openai", "m")
        sources = {
            "survey": RetrievedSource("survey", "customer-research", "Survey found 82 percent intent to buy."),
            "orders": RetrievedSource("orders", "commerce", "There are 240 paid preorders for launch."),
        }
        enricher = SourceEvidenceEnricher(
            source_resolver=lambda source_id: sources.get(source_id),
            citation_supports_stance=lambda claim, stance, quote, _content: (
                claim == provider_claim.claim
                and stance == Stance.SUPPORT
                and ("intent to buy" in quote or "paid preorders" in quote)
            ),
        )
        evidence = enricher.enrich(
            (provider_claim,),
            (
                SourceBackedClaim("claim-1", "survey", "Survey found 82 percent intent to buy.", reliability=.95),
                SourceBackedClaim("claim-1", "orders", "There are 240 paid preorders for launch.", reliability=.95),
            ),
        )

        final = NexusOrchestrator().run_evidence_mission(
            "Should we launch?",
            evidence,
            dissent_fn=lambda _question, _evidence: (),
        )

        self.assertEqual(final.value, "YES")
        self.assertTrue(all(item.verified for item in final.grand_council.evidence))
        self.assertEqual(
            {item.source_family for item in final.grand_council.evidence},
            {"customer-research", "commerce"},
        )

    def test_unsupported_or_contradictory_source_stays_fail_closed(self):
        provider_claim = ProviderEvidence("claim-1", "The launch has validated demand", "openai", "m")
        sources = {
            "survey": RetrievedSource("survey", "customer-research", "Survey found no purchase intent."),
            "orders": RetrievedSource("orders", "commerce", "There are zero paid preorders."),
        }
        enricher = SourceEvidenceEnricher(
            source_resolver=lambda source_id: sources.get(source_id),
            citation_supports_stance=lambda _claim, stance, quote, _content: (
                stance == Stance.CHALLENGE
                and ("no purchase intent" in quote or "zero paid preorders" in quote)
            ),
        )
        evidence = enricher.enrich(
            (provider_claim,),
            (
                SourceBackedClaim(
                    "claim-1", "survey", "Survey found no purchase intent.",
                    stance=Stance.CHALLENGE, reliability=.95,
                ),
                SourceBackedClaim(
                    "claim-1", "orders", "There are zero paid preorders.",
                    stance=Stance.CHALLENGE, reliability=.95,
                ),
            ),
        )

        final = NexusOrchestrator().run_evidence_mission(
            "Should we launch?",
            evidence,
            dissent_fn=lambda _question, _evidence: (),
        )

        self.assertEqual(final.value, "NO")
        self.assertTrue(all(item.verified for item in final.grand_council.evidence))
        self.assertFalse(final.pipeline_passes["grand_council"])

    def test_quote_must_exist_in_independently_retrieved_content(self):
        provider_claim = ProviderEvidence("claim-1", "Demand exists", "openai", "m")
        enricher = SourceEvidenceEnricher(
            source_resolver=lambda _source_id: RetrievedSource("survey", "research", "No matching text."),
            citation_supports_stance=lambda _claim, _stance, _quote, _content: True,
        )
        evidence = enricher.enrich(
            (provider_claim,),
            (SourceBackedClaim("claim-1", "survey", "Invented quotation"),),
        )
        self.assertFalse(evidence[0].verified)

    def test_unknown_provider_evidence_reference_is_rejected(self):
        enricher = SourceEvidenceEnricher(
            source_resolver=lambda _source_id: None,
            citation_supports_stance=lambda _claim, _stance, _quote, _content: False,
        )
        with self.assertRaisesRegex(ValueError, "unknown provider evidence"):
            enricher.enrich(
                (ProviderEvidence("claim-1", "Demand exists", "openai", "m"),),
                (SourceBackedClaim("missing", "survey", "quote"),),
            )

    def test_verified_yes_persists_provider_provenance_and_semantic_memory(self):
        with tempfile.TemporaryDirectory() as td:
            database = Path(td) / "n.db"
            claim = ProviderEvidence(
                "claim-1", "The launch has validated demand", "openai", "fixture-model",
                request_id="req-1", agent="research", attempts=2, latency_ms=7,
            )
            sources = {
                "survey": RetrievedSource("survey", "customer-research", "82 percent intent to buy."),
                "orders": RetrievedSource("orders", "commerce", "240 paid preorders."),
            }
            evidence = SourceEvidenceEnricher(
                lambda source_id: sources.get(source_id),
                lambda _claim, stance, quote, _content: (
                    stance == Stance.SUPPORT and ("intent" in quote or "preorders" in quote)
                ),
            ).enrich(
                (claim,),
                (
                    SourceBackedClaim("claim-1", "survey", "82 percent intent to buy.", reliability=.95),
                    SourceBackedClaim("claim-1", "orders", "240 paid preorders.", reliability=.95),
                ),
            )
            with SQLiteStateStore(database) as store:
                final = NexusOrchestrator(
                    state_store=store,
                    memory_embedding_fn=lambda _text: (1.0, 0.0),
                ).run_evidence_mission(
                    "Should we launch?", evidence,
                    dissent_fn=lambda _question, _evidence: (), run_id="approved-run",
                )
                self.assertEqual(final.value, "YES")

            with SQLiteStateStore(database) as reopened:
                persisted = reopened.list_evidence("approved-run")
                self.assertTrue(all(item.provider == "openai" for item in persisted))
                self.assertTrue(all(item.provider_model == "fixture-model" for item in persisted))
                self.assertTrue(all(item.provider_request_id == "req-1" for item in persisted))
                self.assertTrue(all(item.provider_attempts == 2 for item in persisted))
                memory = reopened.list_memory("verified-runs")
                self.assertEqual(len(memory), 1)
                self.assertEqual(memory[0].metadata["run_id"], "approved-run")
                self.assertEqual(memory[0].metadata["final_value"], "YES")

    def test_rejected_run_does_not_write_semantic_memory(self):
        with tempfile.TemporaryDirectory() as td:
            with SQLiteStateStore(Path(td) / "n.db") as store:
                final = NexusOrchestrator(
                    state_store=store,
                    memory_embedding_fn=lambda _text: (1.0, 0.0),
                ).run_provider_mission(
                    "Should we launch?",
                    (
                        ProviderEvidence("e1", "claim one", "openai", "m"),
                        ProviderEvidence("e2", "claim two", "anthropic", "m"),
                    ),
                    dissent_fn=lambda _question, _evidence: (), run_id="rejected-run",
                )
                self.assertEqual(final.value, "NO")
                self.assertEqual(store.list_memory("verified-runs"), ())


if __name__ == "__main__":
    unittest.main()
