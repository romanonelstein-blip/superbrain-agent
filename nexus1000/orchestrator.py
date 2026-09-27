from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Sequence
from uuid import uuid4

from .councils import SpecialistCouncil
from .dissent import BlindedDissent
from .genesis import ExpertiseGapDetector, GenesisBudget, SpecialistGenesisEngine, SpecialistBlueprint
from .grand_council import GrandCouncil, GrandCouncilConfig, EscalationBudget
from .judge import FinalJudge
from .models import CouncilVerdict, Evidence, FinalDecision
from .neis import NEIS, NEISConfig
from .observability import Timeline
from .routing import AdaptiveRouter, ModelProfile, RoutePlan, RouteRequest, RoutingBudget, ToolProfile
from .policy import AgentPrincipal, PolicyEngine, ToolExecutor, ToolRegistry, ToolRequest
from .durable import CheckpointStore, DurableWorkflow, IdempotencyLedger, StepDefinition, WorkflowState
from .messaging import InMemoryMessageBus, Message, Worker, WorkerConfig, WorkerCoordinator
from .verifier import Verifier
from .persistence import EvidenceRecord, RunRecord, SemanticMemory, SQLiteStateStore
from .provider_bridge import ProviderEvidence, councils_from_evidence, councils_from_provider_evidence
from .learning import ControlledLearningLoop, LearningOutcome, ReflectionContext


@dataclass(frozen=True)
class NexusConfig:
    neis: NEISConfig = field(default_factory=NEISConfig)
    grand_council: GrandCouncilConfig = field(default_factory=GrandCouncilConfig)
    escalation: EscalationBudget = field(default_factory=EscalationBudget)
    genesis: GenesisBudget = field(default_factory=GenesisBudget)
    routing: RoutingBudget = field(default_factory=RoutingBudget)


class NexusOrchestrator:
    def __init__(
        self,
        config: NexusConfig | None = None,
        capability_registry: set[str] | None = None,
        model_registry: tuple[ModelProfile, ...] = (),
        tool_registry: tuple[ToolProfile, ...] = (),
        state_store: SQLiteStateStore | None = None,
        memory_embedding_fn: Callable[[str], Sequence[float]] | None = None,
        learning_loop: ControlledLearningLoop | None = None,
    ) -> None:
        self.config = config or NexusConfig()
        self.neis = NEIS(self.config.neis)
        self.grand = GrandCouncil(self.neis, self.config.grand_council, self.config.escalation)
        self.dissent = BlindedDissent()
        self.verifier = Verifier()
        self.judge = FinalJudge()
        self.timeline = Timeline()
        self.gap_detector = ExpertiseGapDetector()
        self.genesis = SpecialistGenesisEngine(
            capability_registry or {"web_search", "database_read", "document_read", "calculation"},
            self.config.genesis,
        )
        self.router = AdaptiveRouter(
            models=model_registry,
            tools=tool_registry,
            budget=self.config.routing,
        )
        self.last_route_plan: RoutePlan | None = None
        self.tool_registry: ToolRegistry | None = None
        self.policy_engine: PolicyEngine | None = None
        self.tool_executor: ToolExecutor | None = None
        self.state_store = state_store
        self.memory_embedding_fn = memory_embedding_fn
        self.learning_loop = learning_loop
        self.last_learning_outcome: LearningOutcome | None = None




    def build_worker_coordinator(
        self,
        clock,
        worker_specs: list[tuple[WorkerConfig, Callable[[Message], object]]],
    ) -> WorkerCoordinator:
        bus = InMemoryMessageBus(clock)
        coordinator = WorkerCoordinator(bus)
        for config, handler in worker_specs:
            coordinator.register(Worker(bus, config, handler))
        self.timeline.emit(
            "workers",
            f"registered={len(worker_specs)}",
        )
        return coordinator

    def run_durable_workflow(
        self,
        run_id: str,
        steps: list[StepDefinition],
        handlers: dict[str, Callable[[WorkflowState], object]],
        checkpoint_dir: str,
        crash_after_step: str | None = None,
    ) -> WorkflowState:
        store = CheckpointStore(checkpoint_dir)
        workflow = DurableWorkflow(
            run_id=run_id,
            steps=steps,
            store=store,
            ledger=IdempotencyLedger(),
        )
        self.timeline.emit("workflow", f"run={run_id}; durable_start")
        try:
            state = workflow.run(handlers, crash_after_step=crash_after_step)
        except RuntimeError:
            self.timeline.emit("workflow_crash", f"run={run_id}; checkpointed")
            raise
        self.timeline.emit("workflow", f"run={run_id}; status={state.status}")
        return state

    def attach_policy_layer(
        self,
        registry: ToolRegistry,
        policy_engine: PolicyEngine,
    ) -> None:
        if policy_engine.registry is not registry:
            raise ValueError("policy engine and executor must use the same tool registry")
        self.tool_registry = registry
        self.policy_engine = policy_engine
        self.tool_executor = ToolExecutor(registry, policy_engine)
        self.timeline.emit("policy", "policy/tool registry attached")

    def execute_tool(
        self,
        principal: AgentPrincipal,
        request: ToolRequest,
        *args,
        **kwargs,
    ):
        if self.tool_executor is None:
            raise RuntimeError("policy/tool registry not attached")
        self.timeline.emit(
            "tool_request",
            f"agent={request.agent_id}; tool={request.tool_id}; capability={request.capability}",
        )
        try:
            result = self.tool_executor.execute(principal, request, *args, **kwargs)
        except PermissionError as exc:
            self.timeline.emit(
                "tool_denied",
                f"agent={request.agent_id}; tool={request.tool_id}; reason={exc}",
            )
            raise
        self.timeline.emit(
            "tool_allowed",
            f"agent={request.agent_id}; tool={request.tool_id}",
        )
        return result

    def _evaluate(
        self,
        question: str,
        verdicts: list[CouncilVerdict],
        escalate_fn: Callable[[int, tuple[Evidence, ...]], list[CouncilVerdict]] | None,
        dissent_fn: Callable[[str, tuple[Evidence, ...]], tuple[Evidence, ...]] | None,
    ) -> FinalDecision:
        grand = self.grand.adjudicate(verdicts, escalate_fn=escalate_fn)
        self.timeline.emit(
            "grand_council",
            f"provisional_yes={grand.provisional_yes}; stop={grand.stop_reason}",
        )

        neis_result = self.neis.evaluate(grand.evidence)
        self.timeline.emit(
            "neis",
            f"passed={neis_result.passed}; quarantined={len(neis_result.quarantined_ids)}",
        )

        dissent = self.dissent.evaluate(question, neis_result.usable, dissent_fn)
        self.timeline.emit("blinded_dissent", f"passed={dissent.passed}")

        verification = self.verifier.verify(
            neis_result.usable,
            grand.unresolved_conflict,
        )
        self.timeline.emit("verifier", f"passed={verification.passed}")

        final = self.judge.decide(grand, neis_result.passed, dissent, verification)
        self.timeline.emit("final_judge", final.value)
        return final

    def run(
        self,
        question: str,
        councils: list[SpecialistCouncil],
        escalate_fn: Callable[[int, tuple[Evidence, ...]], list[CouncilVerdict]] | None = None,
        dissent_fn: Callable[[str, tuple[Evidence, ...]], tuple[Evidence, ...]] | None = None,
        required_domains: dict[str, tuple[str, ...]] | None = None,
        genesis_runner_factory: Callable[[SpecialistBlueprint], Callable[[str], CouncilVerdict]] | None = None,
        route_request: RouteRequest | None = None,
        run_id: str | None = None,
    ) -> FinalDecision:
        persisted_run_id = run_id or str(uuid4())
        started_at = datetime.now(timezone.utc).isoformat()
        timeline_start = len(self.timeline.events)
        if self.state_store is not None:
            self.state_store.upsert_run(RunRecord(
                persisted_run_id, "running", question, started_at, started_at
            ))
        active_councils = list(councils)

        if route_request is not None:
            plan = self.router.plan(route_request, active_councils)
            self.last_route_plan = plan
            selected_ids = set(plan.council_ids)
            active_councils = [c for c in active_councils if c.council_id in selected_ids]
            self.timeline.emit(
                "adaptive_routing",
                (
                    f"councils={len(plan.council_ids)}; "
                    f"models={len(plan.model_ids)}; tools={len(plan.tool_ids)}; "
                    f"cost={plan.estimated_cost_score}; fallback={plan.fallback_used}"
                ),
            )

        self.timeline.emit("swarm", f"starting {len(active_councils)} specialist councils")
        verdicts = [c.run(question) for c in active_councils]
        self.timeline.emit("councils", f"received {len(verdicts)} council verdicts")

        # Genesis fills explicit expertise gaps left after routing.
        if required_domains and genesis_runner_factory:
            raw_evidence = tuple(e for v in verdicts for e in v.evidence)
            gaps = self.gap_detector.detect(
                required_domains=required_domains,
                active_specialties=[c.specialty for c in active_councils],
                evidence=raw_evidence,
            )
            self.timeline.emit("genesis_gap_detection", f"gaps={len(gaps)}")

            blueprints = self.genesis.create_blueprints(gaps)
            self.timeline.emit("genesis_blueprints", f"created={len(blueprints)}")

            for bp in blueprints:
                specialist = self.genesis.instantiate(bp, genesis_runner_factory)
                verdict = specialist.run(question)
                verdicts.append(verdict)
                self.timeline.emit(
                    "genesis_specialist",
                    f"{bp.specialist_id} returned {len(verdict.evidence)} evidence items",
                )

        final = self._evaluate(
            question=question,
            verdicts=verdicts,
            escalate_fn=escalate_fn,
            dissent_fn=dissent_fn,
        )
        memory_text: str | None = None
        memory_embedding: tuple[float, ...] | None = None
        if (
            self.state_store is not None
            and self.memory_embedding_fn is not None
            and final.value == "YES"
            and final.pipeline_passes.get("verifier", False)
        ):
            memory_text = f"Mission: {question}\nVerified decision: {final.value}"
            memory_embedding = tuple(float(value) for value in self.memory_embedding_fn(memory_text))
            if not memory_embedding:
                raise ValueError("memory embedding cannot be empty")
        if self.state_store is not None:
            for evidence in final.grand_council.evidence:
                self.state_store.put_evidence(EvidenceRecord(
                    evidence.id, persisted_run_id, evidence.claim, evidence.stance.value,
                    evidence.source_id, evidence.source_family, evidence.reliability,
                    evidence.freshness, evidence.relevance, evidence.verified,
                    evidence.citation, evidence.content_hash, evidence.retrieved_at,
                    evidence.location, evidence.content_type,
                    evidence.provider, evidence.provider_model, evidence.provider_request_id,
                    evidence.provider_agent, evidence.provider_attempts,
                    evidence.provider_latency_ms,
                ))
        self.last_learning_outcome = None
        if self.learning_loop is not None:
            if not final.pipeline_passes.get("verifier", False):
                self.timeline.emit("reflection", "skipped: verifier gate did not pass")
            else:
                quarantined_ids = set(final.grand_council.quarantined_evidence_ids)
                reflection_evidence = tuple(
                    evidence
                    for evidence in final.grand_council.evidence
                    if evidence.id not in quarantined_ids
                )
                self.timeline.emit(
                    "reflection",
                    f"started; evidence={len(reflection_evidence)}",
                )
                try:
                    self.last_learning_outcome = self.learning_loop.run(ReflectionContext(
                        run_id=persisted_run_id,
                        mission=question,
                        final_value=final.value,
                        pipeline_passes=dict(final.pipeline_passes),
                        evidence=reflection_evidence,
                    ))
                except Exception as exc:
                    self.timeline.emit("reflection", f"failed: {type(exc).__name__}")
                    if self.state_store is not None:
                        failed_at = datetime.now(timezone.utc).isoformat()
                        self.state_store.upsert_run(RunRecord(
                            persisted_run_id,
                            "reflection_failed",
                            question,
                            started_at,
                            failed_at,
                            final.value,
                        ))
                        self.state_store.replace_run_audit(
                            persisted_run_id,
                            tuple(
                                (event.stage, event.message)
                                for event in self.timeline.events[timeline_start:]
                            ),
                        )
                    raise
                self.timeline.emit(
                    "learning_store",
                    f"lessons={len(self.last_learning_outcome.lessons)}",
                )
                self.timeline.emit(
                    "improvement_candidates",
                    f"proposed={len(self.last_learning_outcome.improvement_candidates)}; applied=0",
                )
        if self.state_store is not None:
            completed_at = datetime.now(timezone.utc).isoformat()
            self.state_store.upsert_run(RunRecord(
                persisted_run_id, "completed", question, started_at, completed_at, final.value
            ))
            if memory_text is not None and memory_embedding is not None:
                SemanticMemory(self.state_store).remember(
                    memory_id=f"run:{persisted_run_id}",
                    namespace="verified-runs",
                    text=memory_text,
                    embedding=memory_embedding,
                    metadata={
                        "run_id": persisted_run_id,
                        "final_value": final.value,
                        "evidence_ids": [evidence.id for evidence in final.grand_council.evidence],
                        "source_ids": [evidence.source_id for evidence in final.grand_council.evidence],
                    },
                )
                self.timeline.emit("memory", "verified run persisted to semantic memory")
            self.state_store.replace_run_audit(
                persisted_run_id,
                tuple((event.stage, event.message) for event in self.timeline.events[timeline_start:]),
            )
        return final

    def run_provider_mission(
        self,
        question: str,
        provider_evidence: tuple[ProviderEvidence, ...],
        *,
        dissent_fn: Callable[[str, tuple[Evidence, ...]], tuple[Evidence, ...]] | None = None,
        run_id: str | None = None,
    ) -> FinalDecision:
        if not provider_evidence:
            raise ValueError("provider mission returned no evidence")
        return self.run(
            question,
            councils_from_provider_evidence(provider_evidence),
            dissent_fn=dissent_fn,
            run_id=run_id,
        )

    def run_evidence_mission(
        self,
        question: str,
        evidence: tuple[Evidence, ...],
        *,
        dissent_fn: Callable[[str, tuple[Evidence, ...]], tuple[Evidence, ...]] | None = None,
        run_id: str | None = None,
    ) -> FinalDecision:
        if not evidence:
            raise ValueError("evidence mission returned no evidence")
        return self.run(
            question,
            councils_from_evidence(evidence),
            dissent_fn=dissent_fn,
            run_id=run_id,
        )
