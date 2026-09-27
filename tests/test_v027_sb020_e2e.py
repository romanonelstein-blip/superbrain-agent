import unittest

from nexus1000.sb020_apply import run_apply


class TestSB020EndToEnd(unittest.TestCase):
    def test_human_approved_eligible_experiment_applies_once_and_passes_post_apply_gates(self):
        result = run_apply()
        self.assertEqual(result["milestone"], "SB-020")
        self.assertEqual(result["experiment"]["decision"], "ELIGIBLE_FOR_APPROVAL")
        self.assertTrue(result["approval"]["signature_verified"])
        self.assertEqual(result["approval"]["signer_kind"], "HUMAN")
        self.assertTrue(result["approval"]["consumed_once"])
        self.assertEqual(result["transaction"]["status"], "APPLIED")
        self.assertEqual(result["post_apply"]["accuracy"], 1.0)
        self.assertEqual(result["post_apply"]["evidence_quality"], 1.0)
        self.assertGreater(result["post_apply"]["calibration_score"], 0.8079)
        self.assertNotEqual(result["target"]["before_sha256"], result["target"]["after_sha256"])
        self.assertFalse(result["deployment_performed"])
        self.assertEqual(result["trace"][-1], "transaction_committed")


if __name__ == "__main__": unittest.main()
