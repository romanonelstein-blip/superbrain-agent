# SB-031 — Context, Recovery & Memory Optimization

Implemented on top of SB-030.

## Capabilities
- **Context management:** selects essential/relevant/recency-weighted context, removes duplicate content, and enforces item/character budgets. Durable history is not blindly replayed.
- **Automatic recovery:** bounded retry with a last-known-good checkpoint fallback. Recovery never bypasses Nexus or assurance gates.
- **Memory optimization:** semantic memory retrieval can filter to essential memories; compaction removes only explicitly non-essential low-value history and preserves essential memory.
- **Autonomous loop integration:** mission selection uses context filtering; research execution gets one bounded retry and checkpoint fallback.

## Safety boundaries
- No automatic code, policy, provider, routing, deployment, or high-impact changes.
- Recovery failure blocks the autonomous step rather than fabricating a result.
- Memory compaction affects retrieval/storage efficiency, not the World Model or immutable decision/audit records.

## Verification
- Full Python suite: **247/247 PASS**
- SB-031 tests: **3/3 PASS**
- Python compile check: PASS
