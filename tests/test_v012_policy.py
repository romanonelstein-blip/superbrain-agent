import unittest

from nexus1000 import (
    AgentPrincipal,
    PolicyEffect,
    PolicyEngine,
    PolicyRule,
    SlidingWindowRateLimiter,
    ToolContract,
    ToolExecutor,
    ToolRegistry,
    ToolRequest,
    ToolRisk,
    NexusOrchestrator,
)


class FakeClock:
    def __init__(self):
        self.t = 0.0
    def __call__(self):
        return self.t
    def advance(self, seconds):
        self.t += seconds


def registry_with_handlers():
    registry = ToolRegistry()
    registry.register(
        ToolContract(
            tool_id="search",
            description="read-only search",
            capabilities=("web_search",),
            required_scopes=("research:read",),
            risk=ToolRisk.LOW,
            mutating=False,
            max_calls_per_window=2,
            window_seconds=10,
        ),
        handler=lambda q: f"search:{q}",
    )
    registry.register(
        ToolContract(
            tool_id="writer",
            description="mutating writer",
            capabilities=("document_write",),
            required_scopes=("docs:write",),
            risk=ToolRisk.HIGH,
            mutating=True,
            max_calls_per_window=5,
            window_seconds=60,
        ),
        handler=lambda x: f"wrote:{x}",
    )
    return registry


class TestRegistry(unittest.TestCase):
    def test_register_and_get(self):
        r = registry_with_handlers()
        self.assertEqual(r.get("search").tool_id, "search")

    def test_duplicate_registration_rejected(self):
        r = ToolRegistry()
        c = ToolContract("x", "x", ("read",))
        r.register(c)
        with self.assertRaises(ValueError):
            r.register(c)

    def test_unknown_tool_raises(self):
        r = ToolRegistry()
        with self.assertRaises(KeyError):
            r.get("missing")


class TestPolicyEngine(unittest.TestCase):
    def setUp(self):
        self.registry = registry_with_handlers()
        self.allow_search = PolicyRule(
            rule_id="allow-research",
            effect=PolicyEffect.ALLOW,
            tools=("search",),
            roles=("researcher",),
            required_scopes=("research:read",),
            max_risk=ToolRisk.LOW,
        )

    def test_default_deny(self):
        engine = PolicyEngine(self.registry, ())
        p = AgentPrincipal("a", roles=("researcher",), scopes=("research:read",))
        d = engine.evaluate(p, ToolRequest("a", "search", "web_search"))
        self.assertFalse(d.allowed)
        self.assertIn("default deny", d.reason)

    def test_allow_rule(self):
        engine = PolicyEngine(self.registry, (self.allow_search,))
        p = AgentPrincipal("a", roles=("researcher",), scopes=("research:read",))
        d = engine.evaluate(p, ToolRequest("a", "search", "web_search"))
        self.assertTrue(d.allowed)

    def test_unknown_tool_denied(self):
        engine = PolicyEngine(self.registry, (self.allow_search,))
        p = AgentPrincipal("a", roles=("researcher",), scopes=("research:read",))
        d = engine.evaluate(p, ToolRequest("a", "nope", "web_search"))
        self.assertFalse(d.allowed)

    def test_undeclared_capability_denied(self):
        engine = PolicyEngine(self.registry, (self.allow_search,))
        p = AgentPrincipal("a", roles=("researcher",), scopes=("research:read",))
        d = engine.evaluate(p, ToolRequest("a", "search", "shell_exec"))
        self.assertFalse(d.allowed)

    def test_principal_hard_deny_wins(self):
        engine = PolicyEngine(self.registry, (self.allow_search,))
        p = AgentPrincipal(
            "a",
            roles=("researcher",),
            scopes=("research:read",),
            denied_tools=("search",),
        )
        d = engine.evaluate(p, ToolRequest("a", "search", "web_search"))
        self.assertFalse(d.allowed)

    def test_principal_allowlist_enforced(self):
        engine = PolicyEngine(self.registry, (self.allow_search,))
        p = AgentPrincipal(
            "a",
            roles=("researcher",),
            scopes=("research:read",),
            allowed_tools=("other",),
        )
        d = engine.evaluate(p, ToolRequest("a", "search", "web_search"))
        self.assertFalse(d.allowed)

    def test_missing_required_scope_denied(self):
        engine = PolicyEngine(self.registry, (self.allow_search,))
        p = AgentPrincipal("a", roles=("researcher",), scopes=())
        d = engine.evaluate(p, ToolRequest("a", "search", "web_search"))
        self.assertFalse(d.allowed)

    def test_explicit_deny_rule_wins_over_allow(self):
        deny = PolicyRule(
            rule_id="deny-search",
            effect=PolicyEffect.DENY,
            tools=("search",),
            roles=("researcher",),
        )
        engine = PolicyEngine(self.registry, (self.allow_search, deny))
        p = AgentPrincipal("a", roles=("researcher",), scopes=("research:read",))
        d = engine.evaluate(p, ToolRequest("a", "search", "web_search"))
        self.assertFalse(d.allowed)
        self.assertIn("deny-search", d.matched_rule_ids)

    def test_agent_mismatch_denied(self):
        engine = PolicyEngine(self.registry, (self.allow_search,))
        p = AgentPrincipal("a", roles=("researcher",), scopes=("research:read",))
        d = engine.evaluate(p, ToolRequest("b", "search", "web_search"))
        self.assertFalse(d.allowed)

    def test_high_risk_mutation_requires_explicit_permissions(self):
        allow_writer_weak = PolicyRule(
            rule_id="weak",
            effect=PolicyEffect.ALLOW,
            tools=("writer",),
            roles=("writer",),
            required_scopes=("docs:write",),
            allow_mutation=False,
            max_risk=ToolRisk.MEDIUM,
        )
        engine = PolicyEngine(self.registry, (allow_writer_weak,))
        p = AgentPrincipal("a", roles=("writer",), scopes=("docs:write",))
        d = engine.evaluate(
            p,
            ToolRequest("a", "writer", "document_write", mutation=True),
        )
        self.assertFalse(d.allowed)

    def test_high_risk_mutation_can_be_explicitly_allowed(self):
        allow_writer = PolicyRule(
            rule_id="writer-ok",
            effect=PolicyEffect.ALLOW,
            tools=("writer",),
            roles=("writer",),
            required_scopes=("docs:write",),
            allow_mutation=True,
            max_risk=ToolRisk.HIGH,
        )
        engine = PolicyEngine(self.registry, (allow_writer,))
        p = AgentPrincipal("a", roles=("writer",), scopes=("docs:write",))
        d = engine.evaluate(
            p,
            ToolRequest("a", "writer", "document_write", mutation=True),
        )
        self.assertTrue(d.allowed)

    def test_audit_records_allow_and_deny(self):
        engine = PolicyEngine(self.registry, (self.allow_search,))
        p = AgentPrincipal("a", roles=("researcher",), scopes=("research:read",))
        engine.evaluate(p, ToolRequest("a", "search", "web_search"))
        engine.evaluate(p, ToolRequest("a", "search", "bad"))
        self.assertEqual(len(engine.audit), 2)
        self.assertTrue(engine.audit[0].allowed)
        self.assertFalse(engine.audit[1].allowed)


class TestRateLimits(unittest.TestCase):
    def test_rate_limit_and_window_reset(self):
        clock = FakeClock()
        limiter = SlidingWindowRateLimiter(clock)
        registry = registry_with_handlers()
        allow = PolicyRule(
            "allow",
            PolicyEffect.ALLOW,
            tools=("search",),
            roles=("researcher",),
            required_scopes=("research:read",),
            max_risk=ToolRisk.LOW,
        )
        engine = PolicyEngine(registry, (allow,), limiter)
        p = AgentPrincipal("a", roles=("researcher",), scopes=("research:read",))
        req = ToolRequest("a", "search", "web_search")

        self.assertTrue(engine.evaluate(p, req).allowed)
        self.assertTrue(engine.evaluate(p, req).allowed)
        self.assertFalse(engine.evaluate(p, req).allowed)

        clock.advance(11)
        self.assertTrue(engine.evaluate(p, req).allowed)

    def test_rate_limits_are_per_agent(self):
        clock = FakeClock()
        limiter = SlidingWindowRateLimiter(clock)
        registry = registry_with_handlers()
        allow = PolicyRule(
            "allow",
            PolicyEffect.ALLOW,
            tools=("search",),
            required_scopes=("research:read",),
            max_risk=ToolRisk.LOW,
        )
        engine = PolicyEngine(registry, (allow,), limiter)

        a = AgentPrincipal("a", scopes=("research:read",))
        b = AgentPrincipal("b", scopes=("research:read",))
        req_a = ToolRequest("a", "search", "web_search")
        req_b = ToolRequest("b", "search", "web_search")

        self.assertTrue(engine.evaluate(a, req_a).allowed)
        self.assertTrue(engine.evaluate(a, req_a).allowed)
        self.assertFalse(engine.evaluate(a, req_a).allowed)
        self.assertTrue(engine.evaluate(b, req_b).allowed)


class TestExecutionPath(unittest.TestCase):
    def test_executor_calls_handler_only_after_allow(self):
        registry = registry_with_handlers()
        allow = PolicyRule(
            "allow",
            PolicyEffect.ALLOW,
            tools=("search",),
            roles=("researcher",),
            required_scopes=("research:read",),
            max_risk=ToolRisk.LOW,
        )
        engine = PolicyEngine(registry, (allow,))
        executor = ToolExecutor(registry, engine)
        p = AgentPrincipal("a", roles=("researcher",), scopes=("research:read",))
        result = executor.execute(
            p,
            ToolRequest("a", "search", "web_search"),
            "hello",
        )
        self.assertEqual(result, "search:hello")

    def test_executor_blocks_denied_call(self):
        registry = registry_with_handlers()
        engine = PolicyEngine(registry, ())
        executor = ToolExecutor(registry, engine)
        p = AgentPrincipal("a", scopes=("research:read",))
        with self.assertRaises(PermissionError):
            executor.execute(
                p,
                ToolRequest("a", "search", "web_search"),
                "hello",
            )

    def test_orchestrator_audits_tool_allow_and_deny(self):
        registry = registry_with_handlers()
        allow = PolicyRule(
            "allow",
            PolicyEffect.ALLOW,
            tools=("search",),
            roles=("researcher",),
            required_scopes=("research:read",),
            max_risk=ToolRisk.LOW,
        )
        engine = PolicyEngine(registry, (allow,))
        orch = NexusOrchestrator()
        orch.attach_policy_layer(registry, engine)

        p = AgentPrincipal("a", roles=("researcher",), scopes=("research:read",))
        out = orch.execute_tool(
            p,
            ToolRequest("a", "search", "web_search"),
            "q",
        )
        self.assertEqual(out, "search:q")

        with self.assertRaises(PermissionError):
            orch.execute_tool(
                p,
                ToolRequest("a", "writer", "document_write", mutation=True),
                "x",
            )

        stages = [e.stage for e in orch.timeline.events]
        self.assertIn("tool_allowed", stages)
        self.assertIn("tool_denied", stages)

    def test_policy_layer_registry_mismatch_rejected(self):
        r1 = registry_with_handlers()
        r2 = registry_with_handlers()
        engine = PolicyEngine(r1, ())
        orch = NexusOrchestrator()
        with self.assertRaises(ValueError):
            orch.attach_policy_layer(r2, engine)


if __name__ == "__main__":
    unittest.main()
