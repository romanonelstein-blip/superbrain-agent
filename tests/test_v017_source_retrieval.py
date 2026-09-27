import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from nexus1000 import (
    LocalDocumentResolver,
    NexusOrchestrator,
    ProviderEvidence,
    RegisteredDocument,
    RetrievalPolicyError,
    SourceBackedClaim,
    SourceEvidenceEnricher,
    SQLiteStateStore,
    Stance,
)


class TestLocalDocumentResolver(unittest.TestCase):
    def test_registered_document_has_immutable_provenance(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            content = "Survey found 82 percent intent to buy."
            (root / "survey.txt").write_text(content, encoding="utf-8")
            resolver = LocalDocumentResolver(
                root,
                (RegisteredDocument("survey", "customer-research", "survey.txt"),),
                clock=lambda: "2026-09-20T12:00:00+00:00",
            )

            source = resolver("survey")

            self.assertEqual(source.content, content)
            self.assertEqual(source.content_hash, hashlib.sha256(content.encode()).hexdigest())
            self.assertEqual(source.retrieved_at, "2026-09-20T12:00:00+00:00")
            self.assertEqual(source.content_type, "text/plain")
            self.assertEqual(source.location, "survey.txt")

    def test_unknown_source_id_is_not_resolved(self):
        with tempfile.TemporaryDirectory() as td:
            resolver = LocalDocumentResolver(td, ())
            self.assertIsNone(resolver("not-registered"))

    def test_registered_path_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "sources"
            root.mkdir()
            outside = Path(td) / "outside.txt"
            outside.write_text("secret", encoding="utf-8")
            resolver = LocalDocumentResolver(
                root,
                (RegisteredDocument("escape", "test", "../outside.txt"),),
            )
            with self.assertRaisesRegex(RetrievalPolicyError, "outside retrieval root"):
                resolver("escape")

    def test_oversized_document_is_blocked_before_read(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "large.txt").write_text("x" * 11, encoding="utf-8")
            resolver = LocalDocumentResolver(
                root,
                (RegisteredDocument("large", "test", "large.txt"),),
                max_bytes=10,
            )
            with self.assertRaisesRegex(RetrievalPolicyError, "size limit"):
                resolver("large")

    def test_unapproved_file_type_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "payload.exe").write_bytes(b"not executable")
            resolver = LocalDocumentResolver(
                root,
                (RegisteredDocument("payload", "test", "payload.exe"),),
            )
            with self.assertRaisesRegex(RetrievalPolicyError, "file type"):
                resolver("payload")

    def test_registered_but_missing_document_is_explicit_failure(self):
        with tempfile.TemporaryDirectory() as td:
            resolver = LocalDocumentResolver(
                td,
                (RegisteredDocument("missing", "test", "missing.txt"),),
            )
            with self.assertRaisesRegex(RetrievalPolicyError, "unavailable"):
                resolver("missing")

    def test_duplicate_source_registration_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, "duplicate registered source_id"):
                LocalDocumentResolver(
                    td,
                    (
                        RegisteredDocument("duplicate", "one", "one.txt"),
                        RegisteredDocument("duplicate", "two", "two.txt"),
                    ),
                )


class TestRetrievalPersistence(unittest.TestCase):
    def test_retrieval_provenance_survives_full_pipeline_and_reopen(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "survey.txt").write_text(
                "Survey found 82 percent intent to buy.", encoding="utf-8"
            )
            (root / "orders.md").write_text(
                "There are 240 paid preorders for launch.", encoding="utf-8"
            )
            resolver = LocalDocumentResolver(
                root,
                (
                    RegisteredDocument("survey", "customer-research", "survey.txt"),
                    RegisteredDocument("orders", "commerce", "orders.md", "text/markdown"),
                ),
                clock=lambda: "2026-09-20T12:00:00+00:00",
            )
            claim = ProviderEvidence("claim-1", "The launch has validated demand", "openai", "m")
            evidence = SourceEvidenceEnricher(
                resolver,
                lambda _claim, stance, quote, _content: (
                    stance == Stance.SUPPORT
                    and ("intent to buy" in quote or "paid preorders" in quote)
                ),
            ).enrich(
                (claim,),
                (
                    SourceBackedClaim("claim-1", "survey", "Survey found 82 percent intent to buy.", reliability=.95),
                    SourceBackedClaim("claim-1", "orders", "There are 240 paid preorders for launch.", reliability=.95),
                ),
            )
            database = root / "n.db"
            with SQLiteStateStore(database) as store:
                final = NexusOrchestrator(state_store=store).run_evidence_mission(
                    "Should we launch?", evidence,
                    dissent_fn=lambda _question, _evidence: (), run_id="retrieval-run",
                )
                self.assertEqual(final.value, "YES")

            with SQLiteStateStore(database) as reopened:
                persisted = reopened.list_evidence("retrieval-run")
                self.assertEqual(len(persisted), 2)
                self.assertTrue(all(item.content_hash for item in persisted))
                self.assertTrue(all(item.retrieved_at == "2026-09-20T12:00:00+00:00" for item in persisted))
                self.assertEqual({item.location for item in persisted}, {"survey.txt", "orders.md"})
                self.assertEqual({item.citation for item in persisted}, {
                    "Survey found 82 percent intent to buy.",
                    "There are 240 paid preorders for launch.",
                })

    def test_existing_v015_database_is_migrated_in_place(self):
        with tempfile.TemporaryDirectory() as td:
            database = Path(td) / "old.db"
            connection = sqlite3.connect(database)
            connection.execute("""
                CREATE TABLE runs(
                  run_id TEXT PRIMARY KEY,status TEXT NOT NULL,question TEXT NOT NULL,
                  created_at TEXT NOT NULL,updated_at TEXT NOT NULL,final_value TEXT
                )
            """)
            connection.execute("""
                CREATE TABLE evidence(
                  evidence_id TEXT PRIMARY KEY,run_id TEXT NOT NULL,claim TEXT NOT NULL,
                  stance TEXT NOT NULL,source_id TEXT NOT NULL,source_family TEXT NOT NULL,
                  reliability REAL NOT NULL,freshness REAL NOT NULL,relevance REAL NOT NULL,
                  verified INTEGER NOT NULL
                )
            """)
            connection.commit()
            connection.close()

            with SQLiteStateStore(database) as store:
                columns = {row["name"] for row in store.conn.execute("PRAGMA table_info(evidence)")}

            self.assertTrue({"citation", "content_hash", "retrieved_at", "location", "content_type"} <= columns)


if __name__ == "__main__":
    unittest.main()
