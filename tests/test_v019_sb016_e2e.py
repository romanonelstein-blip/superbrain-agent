import unittest

from nexus1000.sb016_mission import run_mission


class TestSB016EndToEnd(unittest.TestCase):
    def test_unified_cross_language_mission(self):
        result = run_mission()
        self.assertEqual(result["final_result"], "YES")
        self.assertEqual(result["provider"]["selected"], "openai")
        self.assertEqual(result["provider"]["attempts"], 2)
        self.assertTrue(all(item["verified"] for item in result["evidence"]))
        self.assertEqual(result["persistence"]["memory_count"], 1)
        self.assertIn("verifier", result["trace"])
        self.assertIn("final_judge", result["trace"])


if __name__ == "__main__":
    unittest.main()
