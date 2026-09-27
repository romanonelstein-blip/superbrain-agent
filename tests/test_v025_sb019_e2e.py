import unittest

from nexus1000.sb019_experiment import run_experiment


class TestSB019EndToEnd(unittest.TestCase):
    def test_proposed_candidate_is_isolated_evaluated_persisted_and_only_marked_eligible(self):
        result = run_experiment()

        self.assertEqual(result["milestone"], "SB-019")
        self.assertEqual(result["candidate"]["source_status"], "PROPOSED")
        self.assertEqual(result["decision"], "ELIGIBLE_FOR_APPROVAL")
        self.assertTrue(result["requires_explicit_approval"])
        self.assertFalse(result["automatic_change_applied"])
        self.assertEqual(result["changes_applied"], 0)
        self.assertEqual(result["persistence"]["status"], "COMPLETED")
        self.assertEqual(result["persistence"]["decision"], "ELIGIBLE_FOR_APPROVAL")
        self.assertEqual(result["persistence"]["artifact_count"], 10)
        self.assertEqual(
            set(result["persistence"]["artifact_roles"]),
            {"CANDIDATE", "CONTRACT", "OUTPUT", "REPORT"},
        )
        self.assertEqual(len(result["snapshot"]["digest"]), 64)
        self.assertEqual(len(result["snapshot"]["suite_digest"]), 64)

        before = result["metrics"]["baseline"]
        after = result["metrics"]["candidate"]
        self.assertEqual(after["accuracy"], before["accuracy"])
        self.assertEqual(after["evidence_quality"], before["evidence_quality"])
        self.assertEqual(after["mean_cost_units"], before["mean_cost_units"])
        self.assertGreater(after["calibration_score"], before["calibration_score"])

        self.assertEqual(
            result["trace"],
            [
                "snapshot_created",
                "sandbox_created",
                "baseline_loaded",
                "candidate_evaluated",
                "sandbox_destroyed",
                "contract_verified",
                "metrics_compared",
                "artifacts_persisted",
                "decision_recorded",
            ],
        )
        self.assertTrue(all(result["timestamps"].values()))


if __name__ == "__main__":
    unittest.main()
