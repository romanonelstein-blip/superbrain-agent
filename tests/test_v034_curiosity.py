import unittest

from nexus1000.curiosity import CuriosityPlanner, CuriosityPolicy, CuriosityRoute
from nexus1000.deep_research import DeepResearchPolicy, KnowledgeGap
from nexus1000.models import Evidence, Stance


class TestCuriosityPlanner(unittest.TestCase):
    def test_counterevidence_is_falsification_and_high_priority(self):
        planner = CuriosityPlanner()
        gaps = (
            KnowledgeGap("support-depth", "need support", 80, Stance.SUPPORT),
            KnowledgeGap("counterevidence", "need challenge", 95, Stance.CHALLENGE),
        )
        decision = planner.assess(
            "Should we launch?",
            gaps,
            (),
            round_number=2,
            remaining_source_budget=8,
            previous_new_sources=2,
        )
        self.assertTrue(decision.continue_research)
        self.assertTrue(decision.falsification_question_present)
        counter = next(q for q in decision.questions if q.gap_code == "counterevidence")
        self.assertTrue(counter.falsification)
        self.assertEqual(counter.route, CuriosityRoute.DEEP_RESEARCH)
        self.assertIn("contrary evidence failure risks", counter.question.casefold())

    def test_build_plan_preserves_stance_and_auditable_purpose(self):
        planner = CuriosityPlanner()
        gaps = (KnowledgeGap("source-diversity", "need diversity", 85, Stance.NEUTRAL),)
        decision = planner.assess(
            "Is this market attractive?",
            gaps,
            (),
            round_number=2,
            remaining_source_budget=6,
            previous_new_sources=2,
        )
        plan = planner.build_plan(
            "Is this market attractive?",
            decision,
            max_results_per_query=3,
            max_sources=6,
        )
        self.assertEqual(len(plan.queries), 1)
        self.assertEqual(plan.queries[0].stance, Stance.NEUTRAL)
        self.assertIn("curiosity:source-diversity", plan.queries[0].purpose)

    def test_no_gaps_stops_without_research(self):
        planner = CuriosityPlanner()
        decision = planner.assess(
            "Should we launch?",
            (),
            (),
            round_number=2,
            remaining_source_budget=5,
            previous_new_sources=2,
        )
        self.assertFalse(decision.continue_research)
        self.assertEqual(decision.stop_reason, "evidence_sufficiency_reached")
        self.assertEqual(decision.questions, ())

    def test_budget_exhaustion_stops(self):
        planner = CuriosityPlanner()
        gaps = (KnowledgeGap("counterevidence", "need challenge", 95, Stance.CHALLENGE),)
        decision = planner.assess(
            "Should we launch?",
            gaps,
            (),
            round_number=2,
            remaining_source_budget=0,
            previous_new_sources=2,
        )
        self.assertFalse(decision.continue_research)
        self.assertEqual(decision.stop_reason, "source_budget_exhausted")

    def test_high_gain_threshold_can_decline_followup(self):
        planner = CuriosityPlanner(CuriosityPolicy(min_expected_information_gain=0.99))
        gaps = (KnowledgeGap("source-diversity", "need diversity", 40, Stance.NEUTRAL),)
        decision = planner.assess(
            "Should we launch?",
            gaps,
            (),
            round_number=4,
            remaining_source_budget=1,
            previous_new_sources=0,
        )
        self.assertFalse(decision.continue_research)
        self.assertEqual(decision.stop_reason, "curiosity_information_gain_low")
        self.assertIn(decision.questions[0].route, {CuriosityRoute.REMEMBER, CuriosityRoute.IGNORE})

    def test_policy_bounds(self):
        with self.assertRaises(ValueError):
            CuriosityPolicy(max_questions=99).validate()
        with self.assertRaises(ValueError):
            CuriosityPolicy(min_expected_information_gain=2.0).validate()


if __name__ == "__main__":
    unittest.main()
