import tempfile
import unittest
from pathlib import Path

from nexus1000.mission_control import MissionControlService


class TestSB022EndToEnd(unittest.TestCase):
    def test_demo_mission_can_be_reviewed_and_master_decision_recorded(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = MissionControlService(Path(temporary) / "mission-control.db")
            result = service.run_demo()
            decision = service.record_master_decision(
                result.run_id,
                "ACCEPT",
                note="Master reviewed the canonical Nexus result.",
            )
            reopened = MissionControlService(Path(temporary) / "mission-control.db")
            detail = reopened.get_mission(result.run_id)

            self.assertEqual(result.final_value, "YES")
            self.assertEqual(detail["run"]["final_value"], "YES")
            self.assertTrue(all(item["verified"] for item in detail["evidence"]))
            self.assertIn("verifier", [event["stage"] for event in detail["audit"]])
            self.assertEqual(detail["master_decisions"][0]["decision_id"], decision.decision_id)
            self.assertEqual(detail["master_decisions"][0]["action"], "ACCEPT")


if __name__ == "__main__":
    unittest.main()
