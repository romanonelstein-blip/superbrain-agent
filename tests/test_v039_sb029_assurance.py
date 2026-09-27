import tempfile
import unittest
from pathlib import Path

from nexus1000.assurance import AssuranceStatus, IntelligenceAssurance
from nexus1000.persistence import SQLiteStateStore


class TestSB029Assurance(unittest.TestCase):
    def test_clean_observation_passes(self):
        result = IntelligenceAssurance().evaluate({
            "evidence_count": 4, "decision": "YES", "source_count": 4,
            "unique_family_count": 4, "independence_warning": False,
            "support": 4, "challenge": 0, "belief_state": "SUPPORTED",
            "evidence_quality": 0.9, "confidence": 0.88,
            "all_accepted_have_provenance": True,
            "previous_state": "UNKNOWN", "current_state": "SUPPORTED",
            "impact": "LOW", "human_authorized": False,
        }, run_id="a1")
        self.assertEqual(result.status, AssuranceStatus.PASS)
        self.assertEqual(result.failed, 0)

    def test_adversarial_source_independence_fails(self):
        result = IntelligenceAssurance().evaluate({
            "evidence_count": 4, "decision": "YES", "source_count": 4,
            "unique_family_count": 1, "independence_warning": False,
            "support": 4, "challenge": 0, "belief_state": "SUPPORTED",
            "evidence_quality": 0.9, "confidence": 0.95,
            "all_accepted_have_provenance": True,
            "previous_state": "UNKNOWN", "current_state": "SUPPORTED",
            "impact": "LOW", "human_authorized": False,
        }, run_id="a2")
        self.assertEqual(result.status, AssuranceStatus.FAIL)
        self.assertIn("independence-001", result.critical_failures)

    def test_persistence(self):
        with tempfile.TemporaryDirectory() as d:
            with SQLiteStateStore(Path(d) / "state.db") as store:
                result = IntelligenceAssurance().evaluate({
                    "evidence_count": 0, "decision": "ABSTAIN",
                    "source_count": 0, "unique_family_count": 0, "independence_warning": False,
                    "support": 0, "challenge": 0, "belief_state": "UNKNOWN",
                    "evidence_quality": 0.0, "confidence": 0.0,
                    "all_accepted_have_provenance": True,
                    "previous_state": "UNKNOWN", "current_state": "UNKNOWN",
                    "impact": "LOW", "human_authorized": False,
                }, run_id="a3")
                store.add_assurance_run("assurance-x", result.to_dict(), "2026-09-21T00:00:00Z")
                rows = store.list_assurance_runs()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["run_id"], "a3")


if __name__ == "__main__":
    unittest.main()
