from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .learning import ControlledLearningLoop, LessonProposal, SQLiteLearningStore
from .orchestrator import NexusOrchestrator
from .persistence import SQLiteStateStore
from .provider_bridge import SourceBackedClaim, SourceEvidenceEnricher, TypeScriptProviderBridge
from .source_retrieval import LocalDocumentResolver, RegisteredDocument


MISSION = "Decide whether the validated-demand launch should proceed."


def run_mission(repository_root: str | Path | None = None) -> dict[str, Any]:
    root = Path(repository_root or Path(__file__).resolve().parents[1])
    integration = root / "integrations" / "superbrain_orchestrator_v2"
    prebuilt = integration / "dist" / "src" / "nexus-bridge-fixture-cli.js"
    if prebuilt.is_file():
        bridge_command = ("node", str(prebuilt.relative_to(integration)))
    else:
        npm = "npm.cmd" if os.name == "nt" else "npm"
        bridge_command = (npm, "run", "nexus-bridge:fixture", "--silent")
    bridge = TypeScriptProviderBridge(integration, command=bridge_command)
    provider_items = bridge.run(MISSION, preferred_agents=("research",))
    if len(provider_items) != 1:
        raise RuntimeError("SB-017 fixture must return exactly one provider claim")
    provider_item = provider_items[0]

    with tempfile.TemporaryDirectory() as temporary:
        workspace = Path(temporary)
        (workspace / "survey.txt").write_text(
            "Independent survey: 82 percent intent to buy.", encoding="utf-8"
        )
        (workspace / "orders.txt").write_text(
            "Commerce ledger: 240 paid preorders.", encoding="utf-8"
        )
        resolver = LocalDocumentResolver(
            workspace,
            (
                RegisteredDocument("survey", "customer-research", "survey.txt"),
                RegisteredDocument("orders", "commerce", "orders.txt"),
            ),
        )
        evidence = SourceEvidenceEnricher(
            resolver,
            lambda claim, stance, quote, _content: (
                claim == "The launch has validated demand."
                and stance.value == "support"
                and ("intent to buy" in quote or "paid preorders" in quote)
            ),
        ).enrich(
            provider_items,
            (
                SourceBackedClaim(
                    provider_item.evidence_id,
                    "survey",
                    "Independent survey: 82 percent intent to buy.",
                    reliability=0.95,
                ),
                SourceBackedClaim(
                    provider_item.evidence_id,
                    "orders",
                    "Commerce ledger: 240 paid preorders.",
                    reliability=0.95,
                ),
            ),
        )

        state_database = workspace / "sb017-state.db"
        learning_database = workspace / "sb017-learning.db"
        with SQLiteStateStore(state_database) as state_store, SQLiteLearningStore(
            learning_database
        ) as learning_store:
            learning_loop = ControlledLearningLoop(
                learning_store,
                lambda reflection: (
                    LessonProposal(
                        category="evidence-quality",
                        lesson=(
                            "Independent customer-research and commerce evidence jointly "
                            "reduced single-source risk."
                        ),
                        evidence_ids=tuple(item.id for item in reflection.evidence),
                        confidence=0.90,
                        improvement_candidate=(
                            "Preserve dual-family evidence collection for launch decisions."
                        ),
                    ),
                ),
            )
            orchestrator = NexusOrchestrator(
                state_store=state_store,
                memory_embedding_fn=lambda _text: (1.0, 0.5, 0.25),
                learning_loop=learning_loop,
            )
            final = orchestrator.run_evidence_mission(
                MISSION,
                evidence,
                dissent_fn=lambda _question, _evidence: (),
                run_id="sb017-e2e",
            )

        with SQLiteStateStore(state_database) as state_store, SQLiteLearningStore(
            learning_database
        ) as learning_store:
            persisted_run = state_store.get_run("sb017-e2e")
            persisted_evidence = state_store.list_evidence("sb017-e2e")
            persisted_memory = state_store.list_memory("verified-runs")
            audit = state_store.list_run_audit("sb017-e2e")
            lessons = learning_store.list_lessons()
            reflections = learning_store.list_reflections()
            candidates = learning_store.list_improvement_candidates()
            lesson_evidence = (
                learning_store.list_lesson_evidence(lessons[0].lesson_id) if lessons else ()
            )

        trace = [
            "mission_input",
            "provider_router",
            "model_execution",
            "evidence_creation",
            "source_retrieval",
            *[stage for stage, _detail in audit],
            "persistence",
            "result",
        ]
        lesson = lessons[0] if lessons else None
        candidate = candidates[0] if candidates else None
        result = {
            "milestone": "SB-017",
            "mission": MISSION,
            "final_result": final.value,
            "pipeline_passes": final.pipeline_passes,
            "provider": {
                "selected": provider_item.provider,
                "model": provider_item.model,
                "agent": provider_item.agent,
                "attempts": provider_item.attempts,
                "request_id": provider_item.request_id,
                "latency_ms": provider_item.latency_ms,
            },
            "persistence": {
                "run_status": persisted_run.status if persisted_run else None,
                "stored_final_value": persisted_run.final_value if persisted_run else None,
                "evidence_count": len(persisted_evidence),
                "memory_count": len(persisted_memory),
                "audit_event_count": len(audit),
            },
            "learning": {
                "reflection_enabled": True,
                "reflection_run_count": len(reflections),
                "reflection": {
                    "run_id": reflections[0].run_id if reflections else None,
                    "mission": reflections[0].mission if reflections else None,
                    "final_value": reflections[0].final_value if reflections else None,
                    "pipeline_passes": reflections[0].pipeline_passes if reflections else None,
                },
                "lesson_count": len(lessons),
                "lesson": {
                    "id": lesson.lesson_id if lesson else None,
                    "category": lesson.category if lesson else None,
                    "text": lesson.lesson if lesson else None,
                    "confidence": lesson.confidence if lesson else None,
                    "occurrences": lesson.occurrences if lesson else None,
                    "latest_run_id": lesson.latest_run_id if lesson else None,
                    "evidence": [
                        {
                            "id": item.evidence_id,
                            "claim": item.claim,
                            "stance": item.stance,
                            "source_id": item.source_id,
                            "source_family": item.source_family,
                            "reliability": item.reliability,
                            "citation": item.citation,
                            "content_hash": item.content_hash,
                            "provider": item.provider,
                            "provider_model": item.provider_model,
                            "provider_request_id": item.provider_request_id,
                            "provider_agent": item.provider_agent,
                        }
                        for item in lesson_evidence
                    ],
                },
                "improvement_candidate": {
                    "id": candidate.candidate_id if candidate else None,
                    "description": candidate.description if candidate else None,
                    "confidence": candidate.confidence if candidate else None,
                    "status": candidate.status if candidate else None,
                    "occurrences": candidate.occurrences if candidate else None,
                },
                "applied_change_count": 0,
            },
            "trace": trace,
        }
        if (
            final.value != "YES"
            or not all(final.pipeline_passes.values())
            or persisted_run is None
            or persisted_run.status != "completed"
            or len(persisted_evidence) != 2
            or len(persisted_memory) != 1
            or len(lessons) != 1
            or len(reflections) != 1
            or len(lesson_evidence) != 2
            or len(candidates) != 1
            or candidate.status != "PROPOSED"
            or "reflection" not in trace
            or provider_item.attempts != 2
        ):
            raise RuntimeError(f"SB-017 end-to-end invariants failed: {result}")
        return result


def main() -> None:
    print(json.dumps(run_mission(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
