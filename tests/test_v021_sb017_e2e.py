import unittest

from nexus1000.sb017_mission import run_mission


class TestSB017EndToEnd(unittest.TestCase):
    def test_unified_mission_reflects_and_persists_evidence_bound_learning(self):
        result = run_mission()

        self.assertEqual(result["final_result"], "YES")
        self.assertTrue(result["pipeline_passes"]["verifier"])
        self.assertEqual(result["learning"]["lesson_count"], 1)
        self.assertEqual(result["learning"]["reflection_run_count"], 1)
        self.assertEqual(result["learning"]["reflection"]["final_value"], "YES")
        self.assertEqual(result["learning"]["lesson"]["occurrences"], 1)
        self.assertEqual(len(result["learning"]["lesson"]["evidence"]), 2)
        self.assertEqual(
            {item["source_family"] for item in result["learning"]["lesson"]["evidence"]},
            {"customer-research", "commerce"},
        )
        self.assertTrue(
            all(item["citation"] and item["content_hash"] for item in result["learning"]["lesson"]["evidence"])
        )
        self.assertTrue(
            all(item["provider"] == "openai" for item in result["learning"]["lesson"]["evidence"])
        )
        self.assertLessEqual(
            result["learning"]["lesson"]["confidence"],
            min(item["reliability"] for item in result["learning"]["lesson"]["evidence"]),
        )
        self.assertEqual(result["learning"]["improvement_candidate"]["status"], "PROPOSED")
        self.assertEqual(result["learning"]["applied_change_count"], 0)

        trace = result["trace"]
        self.assertLess(trace.index("final_judge"), trace.index("reflection"))
        self.assertLess(trace.index("reflection"), trace.index("learning_store"))
        self.assertLess(trace.index("learning_store"), trace.index("improvement_candidates"))


if __name__ == "__main__":
    unittest.main()
