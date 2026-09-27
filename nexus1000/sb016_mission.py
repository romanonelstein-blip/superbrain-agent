from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

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
        raise RuntimeError("SB-016 fixture must return exactly one provider claim")
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
                    reliability=.95,
                ),
                SourceBackedClaim(
                    provider_item.evidence_id,
                    "orders",
                    "Commerce ledger: 240 paid preorders.",
                    reliability=.95,
                ),
            ),
        )

        database = workspace / "sb016.db"
        with SQLiteStateStore(database) as store:
            orchestrator = NexusOrchestrator(
                state_store=store,
                memory_embedding_fn=lambda _text: (1.0, 0.5, 0.25),
            )
            final = orchestrator.run_evidence_mission(
                MISSION,
                evidence,
                dissent_fn=lambda _question, _evidence: (),
                run_id="sb016-e2e",
            )

        with SQLiteStateStore(database) as store:
            persisted_run = store.get_run("sb016-e2e")
            persisted_evidence = store.list_evidence("sb016-e2e")
            persisted_memory = store.list_memory("verified-runs")
            audit = store.list_run_audit("sb016-e2e")

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
        result = {
            "milestone": "SB-016",
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
            "evidence": [
                {
                    "id": item.evidence_id,
                    "source_id": item.source_id,
                    "source_family": item.source_family,
                    "verified": item.verified,
                    "provider": item.provider,
                    "provider_model": item.provider_model,
                    "provider_attempts": item.provider_attempts,
                    "content_hash_present": bool(item.content_hash),
                    "citation_present": bool(item.citation),
                }
                for item in persisted_evidence
            ],
            "persistence": {
                "run_status": persisted_run.status if persisted_run else None,
                "stored_final_value": persisted_run.final_value if persisted_run else None,
                "evidence_count": len(persisted_evidence),
                "memory_count": len(persisted_memory),
                "audit_event_count": len(audit),
            },
            "trace": trace,
        }
        if (
            final.value != "YES"
            or not all(final.pipeline_passes.values())
            or len(persisted_evidence) != 2
            or not all(item.verified for item in persisted_evidence)
            or len(persisted_memory) != 1
            or provider_item.attempts != 2
        ):
            raise RuntimeError(f"SB-016 end-to-end invariants failed: {result}")
        return result


def main() -> None:
    print(json.dumps(run_mission(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
