from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence

from .persistence import MemoryHit, SemanticMemory, SQLiteStateStore, cosine_similarity


@dataclass(frozen=True)
class ContextItem:
    key: str
    text: str
    relevance: float = 0.5
    recency: float = 0.5
    essential: bool = False

    @property
    def score(self) -> float:
        return (0.65 * self.relevance) + (0.25 * self.recency) + (0.10 if self.essential else 0.0)


class ContextManager:
    """Select only decision-relevant context; history remains durable but is not blindly replayed."""

    def select(self, items: Iterable[ContextItem], *, max_items: int = 8, max_chars: int = 6000) -> tuple[ContextItem, ...]:
        if max_items < 1 or max_chars < 100:
            raise ValueError("invalid context limits")
        ranked = sorted(items, key=lambda x: (x.essential, x.score), reverse=True)
        selected: list[ContextItem] = []
        seen: set[str] = set()
        chars = 0
        for item in ranked:
            normalized = " ".join(item.text.split()).casefold()
            if not normalized or normalized in seen:
                continue
            cost = len(item.text)
            if selected and chars + cost > max_chars:
                continue
            selected.append(item)
            seen.add(normalized)
            chars += cost
            if len(selected) >= max_items:
                break
        return tuple(selected)

    def essential_text(self, items: Iterable[ContextItem], **limits: Any) -> str:
        return "\n".join(item.text for item in self.select(items, **limits))


@dataclass(frozen=True)
class RecoveryResult:
    status: str
    value: Any
    attempts: int
    recovered: bool
    used_checkpoint: bool
    error_types: tuple[str, ...]


class RecoveryController:
    """Bounded automatic recovery: retry, then fall back to the last known-good checkpoint."""

    def run(
        self,
        operation: Callable[[], Any],
        *,
        checkpoint: Any = None,
        max_retries: int = 2,
        retry_if: Callable[[Exception], bool] | None = None,
    ) -> RecoveryResult:
        if max_retries < 0 or max_retries > 5:
            raise ValueError("max_retries must be between 0 and 5")
        errors: list[str] = []
        for attempt in range(max_retries + 1):
            try:
                return RecoveryResult("SUCCESS", operation(), attempt + 1, attempt > 0, False, tuple(errors))
            except Exception as exc:
                errors.append(type(exc).__name__)
                if retry_if is not None and not retry_if(exc):
                    break
        if checkpoint is not None:
            return RecoveryResult("RECOVERED", checkpoint, max_retries + 1, True, True, tuple(errors))
        return RecoveryResult("FAILED", None, max_retries + 1, False, False, tuple(errors))


class MemoryOptimizer:
    """Keep durable memory intact while minimizing the memory injected into active reasoning."""

    def __init__(self, store: SQLiteStateStore) -> None:
        self.store = store
        self.memory = SemanticMemory(store)

    def retrieve(self, query_embedding: Sequence[float], *, namespace: str | None = None,
                 top_k: int = 5, min_similarity: float = 0.35,
                 essential_only: bool = False) -> tuple[MemoryHit, ...]:
        hits = self.memory.search(query_embedding, namespace=namespace, top_k=max(top_k, 1) * 3,
                                  min_similarity=min_similarity)
        if essential_only:
            hits = tuple(h for h in hits if bool(h.memory.metadata.get("essential", False)))
        return tuple(hits[:top_k])

    def compact(self, namespace: str, *, keep: int = 100) -> int:
        """Delete only explicitly non-essential, low-value historical memory; never delete essential memory."""
        if keep < 1:
            raise ValueError("keep must be >=1")
        memories = list(self.store.list_memory(namespace))
        if len(memories) <= keep:
            return 0
        ranked = sorted(memories, key=lambda m: (
            bool(m.metadata.get("essential", False)),
            float(m.metadata.get("importance", 0.0)),
            str(m.metadata.get("updated_at", "")),
        ), reverse=True)
        survivors = {m.memory_id for m in ranked[:keep]}
        removable = [m for m in ranked[keep:] if not bool(m.metadata.get("essential", False))]
        for m in removable:
            self.store.conn.execute("DELETE FROM semantic_memory WHERE memory_id=?", (m.memory_id,))
        self.store.conn.commit()
        return len(removable)
