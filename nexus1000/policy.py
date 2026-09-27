from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from time import monotonic
from typing import Callable, Any


class ToolRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PolicyEffect(str, Enum):
    ALLOW = "allow"
    DENY = "deny"


@dataclass(frozen=True)
class ToolContract:
    tool_id: str
    description: str
    capabilities: tuple[str, ...]
    required_scopes: tuple[str, ...] = ()
    risk: ToolRisk = ToolRisk.LOW
    mutating: bool = False
    max_calls_per_window: int = 10
    window_seconds: float = 60.0

    def __post_init__(self) -> None:
        if self.max_calls_per_window < 1:
            raise ValueError("max_calls_per_window must be >= 1")
        if self.window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")


@dataclass(frozen=True)
class AgentPrincipal:
    agent_id: str
    roles: tuple[str, ...] = ()
    scopes: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    denied_tools: tuple[str, ...] = ()


@dataclass(frozen=True)
class PolicyRule:
    rule_id: str
    effect: PolicyEffect
    tools: tuple[str, ...] = ("*",)
    roles: tuple[str, ...] = ()
    required_scopes: tuple[str, ...] = ()
    allow_mutation: bool = False
    max_risk: ToolRisk = ToolRisk.MEDIUM

    def matches_tool(self, tool_id: str) -> bool:
        return "*" in self.tools or tool_id in self.tools


@dataclass(frozen=True)
class ToolRequest:
    agent_id: str
    tool_id: str
    capability: str
    scopes: tuple[str, ...] = ()
    purpose: str = ""
    mutation: bool = False


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str
    matched_rule_ids: tuple[str, ...] = ()
    effective_scopes: tuple[str, ...] = ()


@dataclass(frozen=True)
class AuditEvent:
    agent_id: str
    tool_id: str
    capability: str
    allowed: bool
    reason: str
    mutation: bool


class ToolRegistry:
    def __init__(self) -> None:
        self._contracts: dict[str, ToolContract] = {}
        self._handlers: dict[str, Callable[..., Any]] = {}

    def register(
        self,
        contract: ToolContract,
        handler: Callable[..., Any] | None = None,
    ) -> None:
        if contract.tool_id in self._contracts:
            raise ValueError(f"tool already registered: {contract.tool_id}")
        self._contracts[contract.tool_id] = contract
        if handler is not None:
            self._handlers[contract.tool_id] = handler

    def get(self, tool_id: str) -> ToolContract:
        try:
            return self._contracts[tool_id]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {tool_id}") from exc

    def handler(self, tool_id: str) -> Callable[..., Any]:
        try:
            return self._handlers[tool_id]
        except KeyError as exc:
            raise KeyError(f"no handler registered for tool: {tool_id}") from exc

    def all_contracts(self) -> tuple[ToolContract, ...]:
        return tuple(self._contracts.values())


class SlidingWindowRateLimiter:
    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self.clock = clock or monotonic
        self._calls: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def allow(self, agent_id: str, contract: ToolContract) -> bool:
        key = (agent_id, contract.tool_id)
        now = self.clock()
        q = self._calls[key]
        cutoff = now - contract.window_seconds
        while q and q[0] <= cutoff:
            q.popleft()
        if len(q) >= contract.max_calls_per_window:
            return False
        q.append(now)
        return True

    def current_count(self, agent_id: str, tool_id: str) -> int:
        return len(self._calls[(agent_id, tool_id)])


class PolicyEngine:
    """
    Default-deny policy engine.

    Evaluation order:
    1) tool must exist
    2) capability must be declared by the tool
    3) principal-level hard deny wins
    4) principal allow-list must include the tool when configured
    5) tool-required scopes must be present
    6) matching DENY policy wins
    7) at least one matching ALLOW rule must authorize the request
    8) mutation and risk constraints must pass
    9) rate limit must pass
    """

    _RISK_ORDER = {
        ToolRisk.LOW: 0,
        ToolRisk.MEDIUM: 1,
        ToolRisk.HIGH: 2,
        ToolRisk.CRITICAL: 3,
    }

    def __init__(
        self,
        registry: ToolRegistry,
        rules: tuple[PolicyRule, ...] = (),
        rate_limiter: SlidingWindowRateLimiter | None = None,
    ) -> None:
        self.registry = registry
        self.rules = rules
        self.rate_limiter = rate_limiter or SlidingWindowRateLimiter()
        self.audit: list[AuditEvent] = []

    def _audit(self, req: ToolRequest, decision: PolicyDecision) -> PolicyDecision:
        self.audit.append(
            AuditEvent(
                agent_id=req.agent_id,
                tool_id=req.tool_id,
                capability=req.capability,
                allowed=decision.allowed,
                reason=decision.reason,
                mutation=req.mutation,
            )
        )
        return decision

    def evaluate(self, principal: AgentPrincipal, req: ToolRequest) -> PolicyDecision:
        if principal.agent_id != req.agent_id:
            return self._audit(req, PolicyDecision(False, "principal/request agent mismatch"))

        try:
            contract = self.registry.get(req.tool_id)
        except KeyError:
            return self._audit(req, PolicyDecision(False, "unknown tool"))

        if req.capability not in contract.capabilities:
            return self._audit(req, PolicyDecision(False, "capability not declared by tool"))

        if req.tool_id in principal.denied_tools:
            return self._audit(req, PolicyDecision(False, "tool denied by principal policy"))

        if principal.allowed_tools and req.tool_id not in principal.allowed_tools:
            return self._audit(req, PolicyDecision(False, "tool not present in principal allow-list"))

        effective_scopes = set(principal.scopes) | set(req.scopes)
        missing_contract_scopes = set(contract.required_scopes) - effective_scopes
        if missing_contract_scopes:
            return self._audit(
                req,
                PolicyDecision(
                    False,
                    "missing tool-required scopes",
                    effective_scopes=tuple(sorted(effective_scopes)),
                ),
            )

        matched = [
            r for r in self.rules
            if r.matches_tool(req.tool_id)
            and (not r.roles or bool(set(r.roles) & set(principal.roles)))
        ]

        deny_rules = []
        allow_rules = []

        for rule in matched:
            missing_rule_scopes = set(rule.required_scopes) - effective_scopes
            if missing_rule_scopes:
                continue
            if rule.effect == PolicyEffect.DENY:
                deny_rules.append(rule)
            else:
                allow_rules.append(rule)

        if deny_rules:
            return self._audit(
                req,
                PolicyDecision(
                    False,
                    "explicit deny rule matched",
                    tuple(r.rule_id for r in deny_rules),
                    tuple(sorted(effective_scopes)),
                ),
            )

        if not allow_rules:
            return self._audit(
                req,
                PolicyDecision(
                    False,
                    "default deny: no allow rule matched",
                    effective_scopes=tuple(sorted(effective_scopes)),
                ),
            )

        allowed_by_rule = False
        matching_allow_ids: list[str] = []

        for rule in allow_rules:
            if req.mutation and (not contract.mutating or not rule.allow_mutation):
                continue
            if self._RISK_ORDER[contract.risk] > self._RISK_ORDER[rule.max_risk]:
                continue
            allowed_by_rule = True
            matching_allow_ids.append(rule.rule_id)

        if not allowed_by_rule:
            return self._audit(
                req,
                PolicyDecision(
                    False,
                    "allow rules matched but mutation/risk constraints failed",
                    tuple(r.rule_id for r in allow_rules),
                    tuple(sorted(effective_scopes)),
                ),
            )

        if not self.rate_limiter.allow(req.agent_id, contract):
            return self._audit(
                req,
                PolicyDecision(
                    False,
                    "rate limit exceeded",
                    tuple(matching_allow_ids),
                    tuple(sorted(effective_scopes)),
                ),
            )

        return self._audit(
            req,
            PolicyDecision(
                True,
                "allowed",
                tuple(matching_allow_ids),
                tuple(sorted(effective_scopes)),
            ),
        )


class ToolExecutor:
    """The only supported execution path: policy decision first, handler second."""

    def __init__(self, registry: ToolRegistry, policy: PolicyEngine) -> None:
        self.registry = registry
        self.policy = policy

    def execute(
        self,
        principal: AgentPrincipal,
        request: ToolRequest,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        decision = self.policy.evaluate(principal, request)
        if not decision.allowed:
            raise PermissionError(decision.reason)

        handler = self.registry.handler(request.tool_id)
        return handler(*args, **kwargs)
