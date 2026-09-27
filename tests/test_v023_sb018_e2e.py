import json
import tempfile
import unittest
from pathlib import Path

from nexus1000.sb018_eval import run_evaluation


ROOT = Path(__file__).resolve().parents[1]


class TestSB018EndToEnd(unittest.TestCase):
    def test_current_runtime_and_regression_example_produce_safe_comparisons(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = run_evaluation(ROOT, Path(temporary))

            current = result["current_comparison"]
            rejected = result["regression_example"]
            self.assertTrue(current["decision"]["quality_gate_passed"])
            self.assertEqual(current["decision"]["status"], "NO_PROMOTION")
            self.assertFalse(current["decision"]["automatic_change_applied"])
            self.assertEqual(rejected["decision"]["status"], "REJECTED_REGRESSION")
            self.assertFalse(rejected["decision"]["quality_gate_passed"])
            self.assertFalse(rejected["decision"]["automatic_change_applied"])
            self.assertTrue(
                any("accuracy" in reason for reason in rejected["decision"]["regressions"])
            )
            self.assertTrue(
                any("cost" in reason for reason in rejected["decision"]["regressions"])
            )

            output = Path(temporary)
            expected_files = {
                "sb018-current-comparison.json",
                "sb018-current-comparison.md",
                "sb018-regression-example.json",
                "sb018-regression-example.md",
                "sb018-eval-summary.json",
            }
            self.assertEqual({path.name for path in output.iterdir()}, expected_files)
            summary = json.loads(
                (output / "sb018-eval-summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(summary["milestone"], "SB-018")
            self.assertEqual(summary["golden_task_count"], 5)


if __name__ == "__main__":
    unittest.main()
