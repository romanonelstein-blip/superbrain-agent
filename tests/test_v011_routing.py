import unittest

from nexus1000 import (
    Evidence,
    CouncilVerdict,
    NexusOrchestrator,
    ModelProfile,
    ToolProfile,
    RouteRequest,
    RoutingBudget,
    AdaptiveRouter,
)
from nexus1000.models import Stance
from nexus1000.councils import SpecialistCouncil


def ev(i, family=None):
    return Evidence(
        id=f"r{i}",
        claim=f"claim-{i}",
        stance=Stance.SUPPORT,
        source_id=f"rs{i}",
        source_family=family or f"rf{i}",
        reliability=.9,
        freshness=.9,
        relevance=.9,
        verified=True,
    )


def council(cid, specialty):
    return SpecialistCouncil(
        cid,
        specialty,
        lambda q, cid=cid, specialty=specialty: CouncilVerdict(
            council_id=cid,
            specialty=specialty,
            evidence=(ev(abs(hash(cid)) % 100000, family=cid),),
            confidence=.9,
        ),
    )


class TestAdaptiveRouter(unittest.TestCase):
    def setUp(self):
        self.models = (
            ModelProfile("fast-general", ("general", "finance"), ("web_search",), .72, .2, .2),
            ModelProfile("deep-legal", ("legal",), ("document_read", "web_search"), .93, .7, .7),
            ModelProfile("cheap-legal", ("legal",), ("document_read",), .78, .3, .2),
            ModelProfile("slow-expensive", ("legal",), ("document_read",), .99, .99, .99),
        )
        self.tools = (
            ToolProfile("web", ("web_search",), risk=.1, cost=.1),
            ToolProfile("docs", ("document_read",), risk=.1, cost=.1),
            ToolProfile("shell", ("shell_exec",), risk=.9, cost=.1),
        )

    def test_selects_relevant_council(self):
        router = AdaptiveRouter(self.models, self.tools)
        plan = router.plan(
            RouteRequest(domains=("legal",), required_capabilities=("document_read",)),
            [council("legal-c", "legal"), council("finance-c", "finance")],
        )
        self.assertIn("legal-c", plan.council_ids)
        self.assertNotIn("finance-c", plan.council_ids)

    def test_model_constraints_are_enforced(self):
        router = AdaptiveRouter(self.models, self.tools)
        plan = router.plan(
            RouteRequest(
                domains=("legal",),
                required_capabilities=("document_read",),
                min_quality=.7,
                max_latency=.8,
                max_cost=.8,
            ),
            [council("legal-c", "legal")],
        )
        self.assertNotIn("slow-expensive", plan.model_ids)

    def test_prefers_good_coverage_and_quality(self):
        router = AdaptiveRouter(self.models, self.tools)
        plan = router.plan(
            RouteRequest(domains=("legal",), required_capabilities=("document_read",)),
            [council("legal-c", "legal")],
        )
        self.assertIn("deep-legal", plan.model_ids)

    def test_irrelevant_tool_is_not_selected(self):
        router = AdaptiveRouter(self.models, self.tools)
        plan = router.plan(
            RouteRequest(domains=("legal",), required_capabilities=("document_read",)),
            [council("legal-c", "legal")],
        )
        self.assertNotIn("web", plan.tool_ids)

    def test_high_risk_tool_blocked_by_default(self):
        router = AdaptiveRouter(self.models, self.tools)
        plan = router.plan(
            RouteRequest(domains=("ops",), required_capabilities=("shell_exec",)),
            [council("ops-c", "ops")],
        )
        self.assertNotIn("shell", plan.tool_ids)

    def test_high_risk_tool_can_be_explicitly_allowed(self):
        router = AdaptiveRouter(self.models, self.tools)
        plan = router.plan(
            RouteRequest(
                domains=("ops",),
                required_capabilities=("shell_exec",),
                allow_high_risk_tools=True,
            ),
            [council("ops-c", "ops")],
        )
        self.assertIn("shell", plan.tool_ids)

    def test_council_budget_is_enforced(self):
        router = AdaptiveRouter(
            self.models,
            self.tools,
            RoutingBudget(max_councils=2, max_models=2, max_tools=2),
        )
        plan = router.plan(
            RouteRequest(domains=("legal",)),
            [council(f"c{i}", "legal") for i in range(5)],
        )
        self.assertEqual(len(plan.council_ids), 2)

    def test_model_budget_is_enforced(self):
        router = AdaptiveRouter(
            self.models,
            self.tools,
            RoutingBudget(max_councils=2, max_models=1, max_tools=2),
        )
        plan = router.plan(
            RouteRequest(domains=("legal",), required_capabilities=("document_read",)),
            [council("legal-c", "legal")],
        )
        self.assertEqual(len(plan.model_ids), 1)

    def test_fallback_activates_one_council(self):
        router = AdaptiveRouter(self.models, self.tools)
        plan = router.plan(
            RouteRequest(domains=("medical",)),
            [council("legal-c", "legal"), council("finance-c", "finance")],
        )
        self.assertTrue(plan.fallback_used)
        self.assertEqual(len(plan.council_ids), 1)

    def test_total_cost_budget_trims_resources(self):
        router = AdaptiveRouter(
            self.models,
            self.tools,
            RoutingBudget(
                max_councils=2,
                max_models=3,
                max_tools=3,
                max_total_cost_score=.5,
            ),
        )
        plan = router.plan(
            RouteRequest(
                domains=("legal",),
                required_capabilities=("document_read", "web_search"),
            ),
            [council("legal-c", "legal")],
        )
        self.assertLessEqual(plan.estimated_cost_score, .5 + 1e-9)


class TestRoutingPipeline(unittest.TestCase):
    def test_orchestrator_only_runs_routed_councils(self):
        ran = []

        def mk(cid, specialty, evidence):
            return SpecialistCouncil(
                cid,
                specialty,
                lambda q, cid=cid, specialty=specialty, evidence=evidence: (
                    ran.append(cid) or CouncilVerdict(
                        council_id=cid,
                        specialty=specialty,
                        evidence=tuple(evidence),
                        confidence=.9,
                    )
                ),
            )

        orch = NexusOrchestrator(
            model_registry=(
                ModelProfile("m1", ("legal",), ("document_read",), .9, .2, .2),
            ),
            tool_registry=(
                ToolProfile("docs", ("document_read",), .1, .1),
            ),
        )

        final = orch.run(
            "q",
            [
                mk("legal", "legal", [ev(1, "legal")]),
                mk("finance", "finance", [ev(2, "finance")]),
            ],
            route_request=RouteRequest(
                domains=("legal",),
                required_capabilities=("document_read",),
            ),
            required_domains={
                "legal": ("document_read",),
                "independent-review": ("document_read",),
            },
            genesis_runner_factory=lambda bp: (
                lambda q, bp=bp: CouncilVerdict(
                    council_id=bp.specialist_id,
                    specialty=bp.domain,
                    evidence=(ev(3, bp.domain),),
                    confidence=.9,
                )
            ),
            dissent_fn=lambda q, e: (),
        )

        self.assertEqual(ran, ["legal"])
        self.assertIsNotNone(orch.last_route_plan)
        self.assertIn("legal", orch.last_route_plan.council_ids)
        self.assertIn("adaptive_routing", [e.stage for e in orch.timeline.events])
        self.assertEqual(final.value, "YES")

    def test_routing_cannot_bypass_dissent_gate(self):
        orch = NexusOrchestrator(
            model_registry=(
                ModelProfile("m1", ("legal",), ("document_read",), .9, .2, .2),
            ),
            tool_registry=(
                ToolProfile("docs", ("document_read",), .1, .1),
            ),
        )

        c1 = SpecialistCouncil(
            "legal1",
            "legal",
            lambda q: CouncilVerdict("legal1", "legal", (ev(10, "a"),), .9),
        )
        c2 = SpecialistCouncil(
            "legal2",
            "legal",
            lambda q: CouncilVerdict("legal2", "legal", (ev(11, "b"),), .9),
        )

        final = orch.run(
            "q",
            [c1, c2],
            route_request=RouteRequest(domains=("legal",), required_capabilities=("document_read",)),
            # No dissent provider: must remain NO.
        )
        self.assertEqual(final.value, "NO")
        self.assertFalse(final.pipeline_passes["blinded_dissent"])


if __name__ == "__main__":
    unittest.main()
