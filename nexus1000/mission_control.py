from __future__ import annotations

from .assurance import IntelligenceAssurance

import json
import os
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from .models import Evidence, Stance
from .provider_bridge import ProviderEvidence, TypeScriptProviderBridge
from .orchestrator import NexusOrchestrator
from .persistence import MasterDecisionRecord, SQLiteStateStore
from .research import (
    ResearchEngine, ResearchOutcome, ResearchUnavailableError, build_research_plan,
    configured_search_providers, search_client_from_env, GitHubSearchClient, DuckDuckGoSearchClient,
    SafeResearchSourceFetcher, SearchHit,
)
from .deep_research import DeepResearchEngine, DeepResearchOutcome, DeepResearchPolicy
from .network import EgressConfig, NetworkPolicyError, detect_local_tor_proxy
from .world_model import WorldModel
from .change_engine import ChangeEngine


ALLOWED_MASTER_ACTIONS = {"ACCEPT", "MODIFY", "RESEARCH_MORE", "OVERRIDE", "REJECT"}
MAX_MISSION_CHARS = 20_000
MAX_EVIDENCE_ITEMS = 100


class ProviderUnavailableError(RuntimeError):
    """Raised when interactive missions cannot reach a configured model provider."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class MissionControlResult:
    run_id: str
    mission: str
    status: str
    final_value: str
    pipeline_passes: dict[str, bool]
    evidence_count: int
    audit_event_count: int
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResearchMissionResult:
    run_id: str
    mission: str
    status: str
    research: dict[str, Any]
    draft_responses: tuple[dict[str, Any], ...]
    nexus_final_value: str
    pipeline_passes: dict[str, bool]
    evidence_count: int
    audit_event_count: int
    verification_note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DeepResearchMissionResult:
    run_id: str
    mission: str
    status: str
    deep_research: dict[str, Any]
    draft_responses: tuple[dict[str, Any], ...]
    nexus_final_value: str
    pipeline_passes: dict[str, bool]
    evidence_count: int
    audit_event_count: int
    verification_note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InteractiveMissionResult:
    run_id: str
    mission: str
    status: str
    draft_responses: tuple[dict[str, Any], ...]
    nexus_final_value: str
    pipeline_passes: dict[str, bool]
    evidence_count: int
    audit_event_count: int
    verification_note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MissionControlService:
    """Local control plane for the canonical Nexus runtime.

    This layer does not create a second decision engine. Every executed mission
    delegates its final decision to NexusOrchestrator and reads the durable result
    back from SQLiteStateStore.
    """

    def __init__(
        self,
        database_path: str | Path,
        *,
        provider_runner: Any | None = None,
        repository_root: str | Path | None = None,
        research_engine: ResearchEngine | None = None,
        research_synthesizer: Any | None = None,
        deep_research_engine: DeepResearchEngine | None = None,
    ) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.provider_runner = provider_runner
        self.repository_root = Path(repository_root or Path(__file__).resolve().parents[1])
        self.research_engine = research_engine
        self.research_synthesizer = research_synthesizer
        self.deep_research_engine = deep_research_engine

    @staticmethod
    def configured_providers() -> tuple[str, ...]:
        pairs = (
            ("openai", "OPENAI_API_KEY"),
            ("anthropic", "ANTHROPIC_API_KEY"),
            ("gemini", "GEMINI_API_KEY"),
        )
        return tuple(name for name, env_name in pairs if os.getenv(env_name, "").strip())

    def _run_live_provider(
        self,
        mission: str,
        *,
        context: dict[str, Any] | None = None,
        preferred_agents: tuple[str, ...] | None = None,
    ) -> tuple[ProviderEvidence, ...]:
        providers = self.configured_providers()
        if not providers:
            raise ProviderUnavailableError(
                "No live model provider is configured. Add OPENAI_API_KEY, "
                "ANTHROPIC_API_KEY or GEMINI_API_KEY to .env and restart Mission Control."
            )
        integration = self.repository_root / "integrations" / "superbrain_orchestrator_v2"
        prebuilt = integration / "dist" / "src" / "nexus-bridge-cli.js"
        node = shutil.which("node")
        if node is None:
            raise ProviderUnavailableError(
                "Node.js 20+ is required for model-provider calls. Install Node.js, restart Mission Control, then try again."
            )
        if prebuilt.is_file():
            command = (node, str(prebuilt.relative_to(integration)))
        else:
            npm_name = "npm.cmd" if os.name == "nt" else "npm"
            npm = shutil.which(npm_name)
            if npm is None:
                raise ProviderUnavailableError(
                    "The provider bridge is not prebuilt and npm is unavailable. Install Node.js 20+ and restart Mission Control."
                )
            command = (npm, "run", "nexus-bridge", "--silent")
        return TypeScriptProviderBridge(integration, command=command).run(
            mission, context=context, preferred_agents=preferred_agents
        )

    @staticmethod
    def _validate_mission(mission: str) -> str:
        mission = mission.strip()
        if not mission:
            raise ValueError("mission cannot be empty")
        if len(mission) > MAX_MISSION_CHARS:
            raise ValueError(f"mission exceeds {MAX_MISSION_CHARS} characters")
        return mission

    @staticmethod
    def _evidence_from_payload(items: Iterable[dict[str, Any]]) -> tuple[Evidence, ...]:
        raw = list(items)
        if not raw:
            raise ValueError("at least one evidence item is required")
        if len(raw) > MAX_EVIDENCE_ITEMS:
            raise ValueError(f"evidence exceeds {MAX_EVIDENCE_ITEMS} items")
        evidence: list[Evidence] = []
        seen: set[str] = set()
        for item in raw:
            evidence_id = str(item.get("id", "")).strip()
            if not evidence_id or evidence_id in seen:
                raise ValueError("evidence ids must be non-empty and unique")
            seen.add(evidence_id)
            verified = bool(item.get("verified", False))
            citation = item.get("citation")
            content_hash = item.get("content_hash")
            if verified and (not citation or not content_hash):
                raise ValueError(
                    "verified evidence must include citation and content_hash provenance"
                )
            evidence.append(Evidence(
                id=evidence_id,
                claim=str(item.get("claim", "")).strip(),
                stance=Stance(str(item.get("stance", "neutral"))),
                source_id=str(item.get("source_id", "")).strip(),
                source_family=str(item.get("source_family", "")).strip(),
                reliability=float(item.get("reliability", 0.5)),
                freshness=float(item.get("freshness", 1.0)),
                relevance=float(item.get("relevance", 1.0)),
                verified=verified,
                citation=str(citation) if citation is not None else None,
                content_hash=str(content_hash) if content_hash is not None else None,
                retrieved_at=item.get("retrieved_at"),
                location=item.get("location"),
                content_type=item.get("content_type"),
                provider=item.get("provider"),
                provider_model=item.get("provider_model"),
                provider_request_id=item.get("provider_request_id"),
                provider_agent=item.get("provider_agent"),
                provider_attempts=item.get("provider_attempts"),
                provider_latency_ms=item.get("provider_latency_ms"),
            ))
            if not evidence[-1].claim or not evidence[-1].source_id or not evidence[-1].source_family:
                raise ValueError("evidence claim, source_id and source_family are required")
        return tuple(evidence)

    def execute_evidence_mission(
        self,
        mission: str,
        evidence_payload: Iterable[dict[str, Any]],
        *,
        run_id: str | None = None,
    ) -> MissionControlResult:
        mission = self._validate_mission(mission)
        evidence = self._evidence_from_payload(evidence_payload)
        run_id = run_id or f"mission-{uuid4()}"
        with SQLiteStateStore(self.database_path) as store:
            orchestrator = NexusOrchestrator(state_store=store)
            final = orchestrator.run_evidence_mission(
                mission,
                evidence,
                dissent_fn=lambda _question, _evidence: (),
                run_id=run_id,
            )
            self._update_world_model(store, mission, final, run_id)
            record = store.get_run(run_id)
            audit = store.list_run_audit(run_id)
            persisted = store.list_evidence(run_id)
        if record is None:
            raise RuntimeError("mission completed without a durable run record")
        return MissionControlResult(
            run_id=run_id,
            mission=record.question,
            status=record.status,
            final_value=final.value,
            pipeline_passes=dict(final.pipeline_passes),
            evidence_count=len(persisted),
            audit_event_count=len(audit),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def execute_interactive_mission(
        self,
        mission: str,
        *,
        run_id: str | None = None,
    ) -> InteractiveMissionResult:
        """Run a user-authored mission through the provider boundary and Nexus gates.

        Provider text is returned as a draft response, but remains unverified evidence until
        a later research/source-verification stage promotes it. Nexus remains the only
        final-decision engine.
        """
        mission = self._validate_mission(mission)
        runner = self.provider_runner or self._run_live_provider
        try:
            provider_items = tuple(runner(mission))
        except ProviderUnavailableError:
            raise
        except Exception as exc:
            raise ProviderUnavailableError(
                f"The configured provider could not complete the mission ({type(exc).__name__})."
            ) from exc
        if not provider_items:
            raise ProviderUnavailableError("The configured provider returned no response.")

        run_id = run_id or f"mission-{uuid4()}"
        with SQLiteStateStore(self.database_path) as store:
            orchestrator = NexusOrchestrator(state_store=store)
            final = orchestrator.run_provider_mission(
                mission,
                provider_items,
                dissent_fn=lambda _question, _evidence: (),
                run_id=run_id,
            )
            self._update_world_model(store, mission, final, run_id)
            record = store.get_run(run_id)
            audit = store.list_run_audit(run_id)
            persisted = store.list_evidence(run_id)
        if record is None:
            raise RuntimeError("interactive mission completed without a durable run record")

        drafts = tuple({
            "agent": item.agent,
            "text": item.claim,
            "provider": item.provider,
            "model": item.model,
            "request_id": item.request_id,
            "attempts": item.attempts,
            "latency_ms": item.latency_ms,
            "verified": False,
        } for item in provider_items)
        verifier_passed = bool(final.pipeline_passes.get("verifier", False))
        note = (
            "Nexus verification passed."
            if verifier_passed
            else "Draft model output is visible, but Nexus has not independently source-verified it yet."
        )
        return InteractiveMissionResult(
            run_id=run_id,
            mission=record.question,
            status=record.status,
            draft_responses=drafts,
            nexus_final_value=final.value,
            pipeline_passes=dict(final.pipeline_passes),
            evidence_count=len(persisted),
            audit_event_count=len(audit),
            verification_note=note,
        )

    def _update_world_model(
        self,
        store: SQLiteStateStore,
        mission: str,
        final: Any,
        run_id: str,
    ) -> dict[str, Any]:
        world = WorldModel(store)
        revision = world.revise(
            mission,
            final.grand_council.evidence,
            run_id=run_id,
            now=_utc_now(),
            excluded_evidence_ids=final.grand_council.quarantined_evidence_ids,
        )
        change = ChangeEngine(store).detect(revision, run_id=run_id, now=_utc_now())
        audit_events = (
            (
                "world_model",
                f"state={revision.belief.state.value}; confidence={revision.belief.confidence:.3f}; "
                f"added={len(revision.added_evidence_ids)}; revisions={revision.belief.revision_count}",
            ),
        )
        if change is not None:
            audit_events += ((
                "change_engine",
                f"type={change.event_type}; severity={change.severity}; change_id={change.change_id}",
            ),)
        store.replace_run_audit(run_id, store.list_run_audit(run_id) + audit_events)
        return {"belief": revision.to_dict(), "change": change.to_dict() if change else None}

    def run_assurance(self, observation: dict[str, Any], *, run_id: str = "assurance-manual") -> dict[str, Any]:
        from datetime import datetime, timezone
        import hashlib
        with SQLiteStateStore(self.database_path) as store:
            result = IntelligenceAssurance().evaluate(observation, run_id=run_id)
            assurance_id = "assurance-" + hashlib.sha256(repr(result.to_dict()).encode()).hexdigest()[:24]
            store.add_assurance_run(assurance_id, result.to_dict(), datetime.now(timezone.utc).isoformat())
            payload = result.to_dict()
            payload["assurance_id"] = assurance_id
            return payload

    def list_assurance_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        with SQLiteStateStore(self.database_path) as store:
            return list(store.list_assurance_runs(limit))

    def list_world_beliefs(self, limit: int = 100) -> list[dict[str, Any]]:
        with SQLiteStateStore(self.database_path) as store:
            return [item.to_dict() for item in WorldModel(store).list(limit)]

    def list_changes(self, limit: int = 50, *, unacknowledged_only: bool = False) -> list[dict[str, Any]]:
        with SQLiteStateStore(self.database_path) as store:
            return list(ChangeEngine(store).list(limit, unacknowledged_only=unacknowledged_only))

    def run_autonomous_cycle(self, missions: Iterable[str] | None = None, *, cycle_id: str | None = None) -> dict[str, Any]:
        from .autonomy import AutonomousIntelligenceEngine
        result = AutonomousIntelligenceEngine(self).run_cycle(missions, cycle_id=cycle_id)
        return result.to_dict()

    def list_autonomy_cycles(self, limit: int = 20) -> list[dict[str, Any]]:
        from .autonomy import AutonomousIntelligenceEngine
        return list(AutonomousIntelligenceEngine(self).list_cycles(limit))

    def _osint_provider_probe(
        self,
        name: str,
        client: Any,
        query: str,
        *,
        egress: EgressConfig,
    ) -> dict[str, Any]:
        started = datetime.now(timezone.utc)
        try:
            hits = tuple(client.search(query, 1))
            result: dict[str, Any] = {
                "provider": name,
                "search": "PASS",
                "hits": len(hits),
                "latency_ms": int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
            }
            if not hits:
                result["search"] = "PASS_NO_RESULTS"
                return result
            hit = hits[0]
            result["source_family"] = hit.url.split("/")[2] if "://" in hit.url else hit.url
            try:
                fetched = SafeResearchSourceFetcher(egress=egress).fetch(hit)
                result["retrieval"] = "PASS"
                result["content_type"] = fetched.content_type
                result["content_hash_prefix"] = fetched.content_hash[:16]
            except Exception as exc:
                result["retrieval"] = "FAIL"
                result["retrieval_error"] = type(exc).__name__
            return result
        except Exception as exc:
            return {
                "provider": name,
                "search": "FAIL",
                "error": type(exc).__name__,
                "latency_ms": int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
            }

    def run_osint_diagnostics(self) -> dict[str, Any]:
        """Run a bounded live OSINT probe from the machine hosting Mission Control."""
        egress = EgressConfig.from_env()
        results: list[dict[str, Any]] = []
        configured_sources = {
            item.strip().casefold()
            for item in os.getenv("SUPERBRAIN_RESEARCH_SOURCES", "web,github,duckduckgo").split(",")
            if item.strip()
        }
        if "github" in configured_sources:
            results.append(self._osint_provider_probe(
                "github", GitHubSearchClient(egress=egress), "openai", egress=egress
            ))
        if "duckduckgo" in configured_sources or "ddg" in configured_sources:
            results.append(self._osint_provider_probe(
                "duckduckgo", DuckDuckGoSearchClient(egress=egress), "DuckDuckGo", egress=egress
            ))

        tor_probe = detect_local_tor_proxy()
        tor_result: dict[str, Any] = {
            "local_proxy": f"{tor_probe[0]}:{tor_probe[1]}" if tor_probe else None,
            "status": "NOT_DETECTED",
        }
        if tor_probe:
            try:
                tor_cfg = EgressConfig(
                    mode="tor", proxy_host=tor_probe[0], proxy_port=tor_probe[1],
                    onion_allowlist=("duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczad.onion",),
                    timeout_seconds=min(egress.timeout_seconds, 10.0),
                )
                from .research import _read_https_bytes
                status, _headers, body = _read_https_bytes(
                    "https://check.torproject.org/api/ip",
                    timeout=tor_cfg.timeout_seconds, max_bytes=64_000, egress=tor_cfg,
                    headers={"Accept": "application/json", "User-Agent": "SuperBrain-OSINT-Diagnostic/0.27"},
                )
                payload = json.loads(body.decode("utf-8"))
                tor_result["status"] = "PASS" if status == 200 and payload.get("IsTor") is True else "FAIL"
                tor_result["is_tor"] = bool(payload.get("IsTor"))
            except Exception as exc:
                tor_result["status"] = "FAIL"
                tor_result["error"] = type(exc).__name__
        results.append({"provider": "tor", **tor_result})

        onion_result: dict[str, Any] = {
            "status": "POLICY_ONLY",
            "reason": "explicit onion allowlist remains required",
        }
        if tor_probe:
            onion_host = "duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczad.onion"
            try:
                tor_cfg = EgressConfig(
                    mode="tor", proxy_host=tor_probe[0], proxy_port=tor_probe[1],
                    onion_allowlist=(onion_host,), timeout_seconds=min(egress.timeout_seconds, 10.0)
                )
                onion_hit = SearchHit(
                    "DuckDuckGo onion diagnostic", f"https://{onion_host}/",
                    "Controlled public onion connectivity diagnostic", "tor-diagnostic", 1,
                    "tor diagnostic", Stance.NEUTRAL,
                )
                fetched = SafeResearchSourceFetcher(egress=tor_cfg).fetch(onion_hit)
                onion_result = {
                    "status": "PASS", "content_type": fetched.content_type,
                    "content_hash_prefix": fetched.content_hash[:16],
                }
            except Exception as exc:
                onion_result = {"status": "FAIL", "error": type(exc).__name__}

        provider_ok = all(
            item.get("search") in {"PASS", "PASS_NO_RESULTS"}
            for item in results if item.get("provider") in {"github", "duckduckgo"}
        )
        return {
            "timestamp": _utc_now(),
            "configured_egress": {
                "mode": egress.mode, "privacy_enabled": egress.privacy_enabled,
                "tor_enabled": egress.tor_enabled, "onion_allowlist_count": len(egress.onion_allowlist),
            },
            "providers": results, "onion": onion_result,
            "overall": "PASS" if provider_ok and tor_result["status"] in {"PASS", "NOT_DETECTED"} and onion_result["status"] in {"PASS", "POLICY_ONLY"} else "FAIL",
            "credential_values_exposed": False,
        }

    def _resolve_research_engine(self) -> ResearchEngine:
        if self.research_engine is not None:
            return self.research_engine
        return ResearchEngine(search_client_from_env())

    def _synthesize_research(
        self,
        mission: str,
        outcome: ResearchOutcome,
        nexus_final_value: str,
        pipeline_passes: dict[str, bool],
    ) -> tuple[ProviderEvidence, ...]:
        context = {
            "user_mission": mission,
            "research_sources": [source.to_dict() for source in outcome.sources],
            "nexus_evidence_gate": {
                "value": nexus_final_value,
                "passes": pipeline_passes,
            },
            "rules": [
                "Use only the supplied research sources for factual claims.",
                "Cite source URLs next to the claims they support.",
                "Separate source-backed facts from inference and uncertainty.",
                "Do not claim Nexus verified the natural-language synthesis itself.",
            ],
        }
        task = (
            "Produce a concise but substantive answer to the user's mission using the supplied "
            "research sources. Explain the conclusion, strongest evidence, counter-evidence, "
            "uncertainties and practical next action. "
            f"User mission: {mission}"
        )
        if self.research_synthesizer is not None:
            return tuple(self.research_synthesizer(task, context))
        if not self.configured_providers():
            return ()
        return self._run_live_provider(
            task,
            context=context,
            preferred_agents=("research", "strategy"),
        )

    def execute_research_mission(
        self,
        mission: str,
        *,
        run_id: str | None = None,
        max_results_per_query: int = 3,
        max_sources: int = 6,
    ) -> ResearchMissionResult:
        """Research the public web, validate retrieved source evidence, then synthesize an answer.

        The web-search backend discovers candidate URLs. Source content is independently fetched
        over guarded HTTPS and content-addressed before it can enter Nexus as verified evidence.
        Nexus validates the evidence bundle; model-generated synthesis remains explicitly advisory.
        """
        mission = self._validate_mission(mission)
        plan = build_research_plan(
            mission,
            max_results_per_query=max_results_per_query,
            max_sources=max_sources,
        )
        try:
            outcome = self._resolve_research_engine().run(plan)
        except ResearchUnavailableError:
            raise
        except Exception as exc:
            raise ResearchUnavailableError(
                f"Research could not complete ({type(exc).__name__})."
            ) from exc
        if not outcome.evidence:
            raise ResearchUnavailableError(
                "Web search completed but no source could be safely retrieved and verified."
            )

        run_id = run_id or f"mission-{uuid4()}"
        with SQLiteStateStore(self.database_path) as store:
            orchestrator = NexusOrchestrator(state_store=store)
            final = orchestrator.run_evidence_mission(
                mission,
                outcome.evidence,
                dissent_fn=lambda _question, _evidence: (),
                run_id=run_id,
            )
            self._update_world_model(store, mission, final, run_id)
            research_events = (
                ("research_plan", f"queries={len(plan.queries)}; max_sources={plan.max_sources}"),
                ("web_search", f"provider={outcome.search_provider}; sources={len(outcome.sources)}"),
                ("source_retrieval", f"verified={len(outcome.evidence)}; skipped={len(outcome.skipped_results)}"),
            )
            existing_audit = store.list_run_audit(run_id)
            store.replace_run_audit(run_id, research_events + existing_audit)
            record = store.get_run(run_id)
            audit = store.list_run_audit(run_id)
            persisted = store.list_evidence(run_id)
        if record is None:
            raise RuntimeError("research mission completed without a durable run record")

        try:
            provider_items = self._synthesize_research(
                mission, outcome, final.value, dict(final.pipeline_passes)
            )
        except Exception:
            provider_items = ()
        drafts = tuple({
            "agent": item.agent,
            "text": item.claim,
            "provider": item.provider,
            "model": item.model,
            "request_id": item.request_id,
            "attempts": item.attempts,
            "latency_ms": item.latency_ms,
            "verified": False,
        } for item in provider_items)

        gates_passed = all(final.pipeline_passes.values())
        note = (
            "Retrieved web evidence passed all Nexus evidence gates. The written synthesis is still model-generated and advisory."
            if gates_passed
            else "Web sources were retrieved and content-addressed, but one or more Nexus evidence gates did not pass. Treat the synthesis as advisory and inspect the cited sources."
        )
        if not drafts:
            note += " No model provider was available for natural-language synthesis."

        return ResearchMissionResult(
            run_id=run_id,
            mission=record.question,
            status=record.status,
            research=outcome.to_dict(),
            draft_responses=drafts,
            nexus_final_value=final.value,
            pipeline_passes=dict(final.pipeline_passes),
            evidence_count=len(persisted),
            audit_event_count=len(audit),
            verification_note=note,
        )

    def _resolve_deep_research_engine(self, policy: DeepResearchPolicy) -> DeepResearchEngine:
        if self.deep_research_engine is not None:
            return self.deep_research_engine
        return DeepResearchEngine(self._resolve_research_engine(), policy=policy)

    def execute_deep_research_mission(
        self,
        mission: str,
        *,
        run_id: str | None = None,
        max_rounds: int = 3,
        max_total_sources: int = 12,
        max_results_per_query: int = 3,
    ) -> DeepResearchMissionResult:
        """Run bounded iterative public-web research before the canonical Nexus decision.

        Every round still uses the existing guarded ResearchEngine. The deep layer may request
        another round only to close explicit evidence gaps; it stops on sufficiency, low marginal
        information gain, source budget, or the configured round cap.
        """
        mission = self._validate_mission(mission)
        policy = DeepResearchPolicy(
            max_rounds=max_rounds,
            max_total_sources=max_total_sources,
            max_results_per_query=max_results_per_query,
        )
        policy.validate()
        try:
            outcome = self._resolve_deep_research_engine(policy).run(mission)
        except ResearchUnavailableError:
            raise
        except Exception as exc:
            raise ResearchUnavailableError(
                f"Deep research could not complete ({type(exc).__name__})."
            ) from exc
        if not outcome.evidence:
            raise ResearchUnavailableError(
                "Deep research completed but no source could be safely retrieved and verified."
            )

        run_id = run_id or f"mission-{uuid4()}"
        with SQLiteStateStore(self.database_path) as store:
            orchestrator = NexusOrchestrator(state_store=store)
            final = orchestrator.run_evidence_mission(
                mission,
                outcome.evidence,
                dissent_fn=lambda _question, _evidence: (),
                run_id=run_id,
            )
            self._update_world_model(store, mission, final, run_id)
            research_events: list[tuple[str, str]] = [(
                "deep_research_start",
                f"max_rounds={policy.max_rounds}; max_total_sources={policy.max_total_sources}",
            )]
            for item in outcome.rounds:
                if item.curiosity_decision is not None:
                    research_events.append((
                        "curiosity_plan",
                        f"round={item.round_number}; questions={len(item.curiosity_decision.questions)}; "
                        f"expected_gain={item.curiosity_decision.total_expected_information_gain:.3f}; "
                        f"top_question={item.curiosity_decision.top_question or 'none'}",
                    ))
                research_events.append((
                    "deep_research_round",
                    f"round={item.round_number}; queries={len(item.plan.queries)}; "
                    f"new_sources={len(item.new_source_ids)}; gaps_after={len(item.knowledge_gaps_after)}",
                ))
            research_events.extend((
                ("deep_research_stop", f"reason={outcome.stop_reason}; rounds={len(outcome.rounds)}"),
                ("source_retrieval", f"verified={len(outcome.evidence)}; skipped={len(outcome.skipped_results)}"),
            ))
            existing_audit = store.list_run_audit(run_id)
            store.replace_run_audit(run_id, tuple(research_events) + existing_audit)
            record = store.get_run(run_id)
            audit = store.list_run_audit(run_id)
            persisted = store.list_evidence(run_id)
        if record is None:
            raise RuntimeError("deep research mission completed without a durable run record")

        combined = ResearchOutcome(
            plan=outcome.rounds[0].plan,
            search_provider=outcome.rounds[0].outcome.search_provider,
            sources=outcome.sources,
            evidence=outcome.evidence,
            skipped_results=outcome.skipped_results,
        )
        try:
            provider_items = self._synthesize_research(
                mission, combined, final.value, dict(final.pipeline_passes)
            )
        except Exception:
            provider_items = ()
        drafts = tuple({
            "agent": item.agent,
            "text": item.claim,
            "provider": item.provider,
            "model": item.model,
            "request_id": item.request_id,
            "attempts": item.attempts,
            "latency_ms": item.latency_ms,
            "verified": False,
        } for item in provider_items)

        gates_passed = all(final.pipeline_passes.values())
        note = (
            f"Deep research stopped because '{outcome.stop_reason}' after {len(outcome.rounds)} round(s). "
            + (
                "Aggregated retrieved evidence passed all Nexus evidence gates."
                if gates_passed
                else "One or more Nexus evidence gates did not pass."
            )
        )
        if outcome.knowledge_gaps:
            note += f" {len(outcome.knowledge_gaps)} evidence gap(s) remain explicit."
        if not drafts:
            note += " No model provider was available for natural-language synthesis."

        return DeepResearchMissionResult(
            run_id=run_id,
            mission=record.question,
            status=record.status,
            deep_research=outcome.to_dict(),
            draft_responses=drafts,
            nexus_final_value=final.value,
            pipeline_passes=dict(final.pipeline_passes),
            evidence_count=len(persisted),
            audit_event_count=len(audit),
            verification_note=note,
        )

    def run_demo(self) -> MissionControlResult:
        return self.execute_evidence_mission(
            "Decide whether the validated-demand launch should proceed.",
            (
                {
                    "id": "demo:orders",
                    "claim": "The launch has validated demand.",
                    "stance": "support",
                    "source_id": "orders",
                    "source_family": "commerce",
                    "reliability": 0.95,
                    "verified": True,
                    "citation": "Commerce ledger: 240 paid preorders.",
                    "content_hash": "demo-orders-sha256",
                    "provider": "mission-control-demo",
                    "provider_model": "deterministic",
                    "provider_request_id": "demo",
                    "provider_agent": "research",
                    "provider_attempts": 1,
                    "provider_latency_ms": 0,
                },
                {
                    "id": "demo:survey",
                    "claim": "The launch has validated demand.",
                    "stance": "support",
                    "source_id": "survey",
                    "source_family": "customer-research",
                    "reliability": 0.95,
                    "verified": True,
                    "citation": "Independent survey: 82 percent intent to buy.",
                    "content_hash": "demo-survey-sha256",
                    "provider": "mission-control-demo",
                    "provider_model": "deterministic",
                    "provider_request_id": "demo",
                    "provider_agent": "research",
                    "provider_attempts": 1,
                    "provider_latency_ms": 0,
                },
            ),
        )

    def get_mission(self, run_id: str) -> dict[str, Any] | None:
        with SQLiteStateStore(self.database_path) as store:
            record = store.get_run(run_id)
            if record is None:
                return None
            evidence = store.list_evidence(run_id)
            audit = store.list_run_audit(run_id)
            master = store.list_master_decisions(run_id)
            belief = WorldModel(store).get(WorldModel.belief_id_for(record.question))
        return {
            "run": asdict(record),
            "evidence": [asdict(item) for item in evidence],
            "audit": [{"stage": stage, "detail": detail} for stage, detail in audit],
            "master_decisions": [asdict(item) for item in master],
            "world_model": belief.to_dict() if belief else None,
        }

    def list_missions(self, limit: int = 50) -> list[dict[str, Any]]:
        if limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        with SQLiteStateStore(self.database_path) as store:
            rows = store.list_runs(limit=limit)
        return [asdict(item) for item in rows]

    def record_master_decision(
        self,
        run_id: str,
        action: str,
        *,
        note: str = "",
        desired_outcome: str | None = None,
    ) -> MasterDecisionRecord:
        action = action.strip().upper()
        if action not in ALLOWED_MASTER_ACTIONS:
            raise ValueError(f"unsupported master action: {action}")
        if len(note) > 10_000:
            raise ValueError("master decision note is too long")
        with SQLiteStateStore(self.database_path) as store:
            run = store.get_run(run_id)
            if run is None:
                raise KeyError(run_id)
            record = MasterDecisionRecord(
                decision_id=f"master-{uuid4()}",
                run_id=run_id,
                action=action,
                note=note,
                desired_outcome=desired_outcome,
                created_at=_utc_now(),
            )
            store.put_master_decision(record)
            return record

    def system_status(self) -> dict[str, Any]:
        with SQLiteStateStore(self.database_path) as store:
            runs = store.list_runs(limit=200)
        env_path = self.repository_root / ".env"
        integration = self.repository_root / "integrations" / "superbrain_orchestrator_v2"
        bridge = integration / "dist" / "src" / "nexus-bridge-cli.js"
        node = shutil.which("node")
        node_version = None
        if node is not None:
            try:
                completed = subprocess.run(
                    [node, "--version"], capture_output=True, text=True, timeout=2, check=False
                )
                node_version = (completed.stdout or completed.stderr).strip() or None
            except Exception:
                node_version = None
        providers = list(self.configured_providers())
        search_providers = list(configured_search_providers())
        try:
            egress = EgressConfig.from_env()
            egress_status = {
                "mode": egress.mode,
                "privacy_enabled": egress.privacy_enabled,
                "tor_enabled": egress.tor_enabled,
                "onion_allowlist_count": len(egress.onion_allowlist),
                "onion_research_allowed": bool(egress.tor_enabled and egress.onion_allowlist),
            }
        except NetworkPolicyError as exc:
            egress_status = {"mode": "invalid", "privacy_enabled": False, "error": str(exc)}
        return {
            "service": "superbrain-mission-control",
            "ui_version": "SB-027",
            "build_version": "SB-028",
            "build_version": "SB-027",
            "canonical_runtime": "NexusOrchestrator",
            "database": str(self.database_path),
            "mission_count": len(runs),
            "completed_count": sum(1 for run in runs if run.status == "completed"),
            "live_provider_validation_claimed": False,
            "configured_providers": providers,
            "interactive_missions_available": bool(providers) and node is not None,
            "configured_search_providers": search_providers,
            "research_routing": egress_status,
            "github_integration": {"enabled": "github" in search_providers, "authenticated": bool(os.getenv("GITHUB_TOKEN", "").strip())},
            "duckduckgo_integration": {"enabled": "duckduckgo" in search_providers},
            "research_missions_available": bool(search_providers),
            "deep_research_available": bool(search_providers),
            "curiosity_research_available": bool(search_providers),
            "world_model_available": True,
            "change_engine_available": True,
            "osint_live_diagnostics_available": True,
            "automatic_change_application": False,
            "stealth_mode": os.getenv("SUPERBRAIN_STEALTH_MODE", "1").strip().casefold() in {"1", "true", "yes", "on"},
            "runtime_checks": {
                "python": platform.python_version(),
                "node_available": node is not None,
                "node_version": node_version,
                "provider_bridge_prebuilt": bridge.is_file(),
                "env_file_present": env_path.is_file(),
                "env_file": str(env_path),
            },
        }
