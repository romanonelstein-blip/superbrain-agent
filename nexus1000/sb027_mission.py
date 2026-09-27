from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

from .mission_control import MissionControlService


def _evidence(evidence_id: str, family: str, stance: str) -> dict:
    return {
        "id": evidence_id,
        "claim": f"Deterministic SB-027 {stance} evidence from {family}.",
        "stance": stance,
        "source_id": evidence_id,
        "source_family": family,
        "reliability": 1.0,
        "freshness": 1.0,
        "relevance": 1.0,
        "verified": True,
        "citation": f"https://{family}/evidence",
        "content_hash": hashlib.sha256(evidence_id.encode()).hexdigest(),
        "retrieved_at": "2026-09-21T00:00:00+00:00",
        "location": f"https://{family}/evidence",
        "content_type": "text/html",
    }


def main() -> None:
    mission = "Should the evidence-backed launch proceed?"
    with tempfile.TemporaryDirectory() as temporary:
        service = MissionControlService(Path(temporary) / "state.db")
        first = service.execute_evidence_mission(
            mission,
            [_evidence(f"support-{index}", f"support-{index}.example", "support") for index in range(1, 5)],
            run_id="sb027-acceptance-support",
        )
        second = service.execute_evidence_mission(
            mission,
            [_evidence(f"challenge-{index}", f"challenge-{index}.example", "challenge") for index in range(1, 5)],
            run_id="sb027-acceptance-challenge",
        )
        detail = service.get_mission(second.run_id)
        print(json.dumps({
            "milestone": "SB-027",
            "first_nexus_value": first.final_value,
            "second_nexus_value": second.final_value,
            "world_model": detail["world_model"] if detail else None,
            "world_model_states": [item["state"] for item in service.list_world_beliefs()],
        }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
