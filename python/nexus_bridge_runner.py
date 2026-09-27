from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REQUIRED_GATES = ("grand_council", "neis", "blinded_dissent", "verifier")


def _number(value: Any, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("evidence score must be numeric")
    number = float(value)
    if not 0.0 <= number <= 1.0:
        raise ValueError("evidence score must be in [0, 1]")
    return number


def _required_text(item: dict[str, Any], key: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required")
    return value.strip()


def _build_evidence(item: dict[str, Any]):
    from nexus1000.models import Evidence, Stance

    verified = item.get("verified") is True
    citation = item.get("citation")
    content_hash = item.get("contentHash")
    if verified:
        if not isinstance(citation, str) or not citation.strip():
            raise ValueError("verified evidence requires citation")
        if not isinstance(content_hash, str) or not content_hash.strip():
            raise ValueError("verified evidence requires contentHash")
    stance_raw = item.get("stance", "support")
    try:
        stance = Stance(stance_raw)
    except ValueError as exc:
        raise ValueError("invalid evidence stance") from exc
    return Evidence(
        id=_required_text(item, "id"),
        claim=_required_text(item, "claim"),
        stance=stance,
        source_id=_required_text(item, "sourceId"),
        source_family=_required_text(item, "sourceFamily"),
        reliability=_number(item.get("reliability"), 0.5),
        freshness=_number(item.get("freshness"), 1.0),
        relevance=_number(item.get("relevance"), 1.0),
        verified=verified,
        citation=citation.strip() if isinstance(citation, str) and citation.strip() else None,
        content_hash=content_hash.strip() if isinstance(content_hash, str) and content_hash.strip() else None,
        retrieved_at=item.get("retrievedAt") if isinstance(item.get("retrievedAt"), str) else None,
        location=item.get("location") if isinstance(item.get("location"), str) else None,
        content_type=item.get("contentType") if isinstance(item.get("contentType"), str) else None,
        provider=item.get("provider") if isinstance(item.get("provider"), str) else None,
        provider_model=item.get("providerModel") if isinstance(item.get("providerModel"), str) else None,
        provider_request_id=item.get("providerRequestId") if isinstance(item.get("providerRequestId"), str) else None,
        provider_agent=item.get("providerAgent") if isinstance(item.get("providerAgent"), str) else None,
        provider_attempts=item.get("providerAttempts") if isinstance(item.get("providerAttempts"), int) else None,
        provider_latency_ms=item.get("providerLatencyMs") if isinstance(item.get("providerLatencyMs"), int) else None,
    )


def main() -> int:
    payload = json.load(sys.stdin)
    if not isinstance(payload, dict):
        raise ValueError("request must be an object")
    core_path = payload.get("corePath")
    if not isinstance(core_path, str) or not core_path.strip():
        raise ValueError("corePath is required")
    root = Path(core_path).expanduser().resolve()
    if not (root / "nexus1000" / "orchestrator.py").is_file() or not (root / "nexus1000" / "neis.py").is_file():
        raise ValueError("NEXUS core files not found")
    sys.path.insert(0, str(root))

    question = _required_text(payload, "question")
    raw_evidence = payload.get("evidence")
    if not isinstance(raw_evidence, list) or not raw_evidence:
        raise ValueError("at least one evidence item is required")
    evidence = tuple(_build_evidence(item) for item in raw_evidence if isinstance(item, dict))
    if len(evidence) != len(raw_evidence):
        raise ValueError("every evidence item must be an object")

    dissent_fn = None
    raw_dissent = payload.get("dissent")
    if raw_dissent is not None:
        if not isinstance(raw_dissent, dict) or raw_dissent.get("completed") is not True:
            raise ValueError("dissent must be explicitly completed")
        _required_text(raw_dissent, "provider")
        raw_counter = raw_dissent.get("evidence", [])
        if not isinstance(raw_counter, list):
            raise ValueError("dissent evidence must be a list")
        counterevidence = tuple(_build_evidence(item) for item in raw_counter if isinstance(item, dict))
        if len(counterevidence) != len(raw_counter):
            raise ValueError("every dissent evidence item must be an object")
        dissent_fn = lambda _question, _evidence: counterevidence

    from nexus1000.orchestrator import NexusOrchestrator

    orchestrator = NexusOrchestrator()
    run_id = payload.get("runId") if isinstance(payload.get("runId"), str) else None
    final = orchestrator.run_evidence_mission(question, evidence, dissent_fn=dissent_fn, run_id=run_id)
    passes = {name: final.pipeline_passes.get(name) is True for name in REQUIRED_GATES}
    approved = final.value == "YES" and all(passes.values())
    result = {
        "decision": final.value,
        "approved": approved,
        "pipelinePasses": passes,
        "reasons": list(final.reasons),
        "evidenceIds": [item.id for item in final.grand_council.evidence],
    }
    sys.stdout.write(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        sys.stderr.write(f"NEXUS bridge failed: {type(exc).__name__}\n")
        raise SystemExit(2)
