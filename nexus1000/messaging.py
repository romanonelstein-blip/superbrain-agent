from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class Message:
    message_id: str
    topic: str
    payload: Any
    dedupe_key: str
    max_deliveries: int = 3

    def __post_init__(self) -> None:
        if self.max_deliveries < 1:
            raise ValueError("max_deliveries must be >= 1")


@dataclass
class Delivery:
    message: Message
    delivery_count: int
    worker_id: str
    lease_deadline: float
    acked: bool = False


@dataclass(frozen=True)
class DeadLetter:
    message: Message
    delivery_count: int
    reason: str


class InMemoryMessageBus:
    """
    Deterministic prototype message bus with at-least-once delivery semantics.

    Guarantees:
    - messages are delivered with a visibility lease
    - unacked leases can be redelivered
    - ack removes a message from active delivery
    - nack returns a message to the queue
    - messages exceeding max_deliveries enter the DLQ
    - dedupe_key prevents duplicate completion
    """

    def __init__(self, clock: Callable[[], float]) -> None:
        self.clock = clock
        self._queues: dict[str, deque[Message]] = {}
        self._inflight: dict[str, Delivery] = {}
        self._completed_dedupe_keys: set[str] = set()
        self._delivery_counts: dict[str, int] = {}
        self._dead_letters: list[DeadLetter] = []

    def publish(self, message: Message) -> bool:
        if message.dedupe_key in self._completed_dedupe_keys:
            return False
        self._queues.setdefault(message.topic, deque()).append(message)
        return True

    def _expire_leases(self) -> None:
        now = self.clock()
        expired = [
            mid for mid, delivery in self._inflight.items()
            if not delivery.acked and delivery.lease_deadline <= now
        ]
        for mid in expired:
            delivery = self._inflight.pop(mid)
            msg = delivery.message
            if delivery.delivery_count >= msg.max_deliveries:
                self._dead_letters.append(
                    DeadLetter(msg, delivery.delivery_count, "visibility timeout exhausted")
                )
            else:
                self._queues.setdefault(msg.topic, deque()).appendleft(msg)

    def pull(self, topic: str, worker_id: str, visibility_timeout: float = 30.0) -> Delivery | None:
        if visibility_timeout <= 0:
            raise ValueError("visibility_timeout must be > 0")

        self._expire_leases()
        q = self._queues.setdefault(topic, deque())

        while q:
            msg = q.popleft()

            if msg.dedupe_key in self._completed_dedupe_keys:
                continue

            count = self._delivery_counts.get(msg.message_id, 0) + 1
            self._delivery_counts[msg.message_id] = count

            if count > msg.max_deliveries:
                self._dead_letters.append(
                    DeadLetter(msg, count - 1, "max deliveries exhausted")
                )
                continue

            delivery = Delivery(
                message=msg,
                delivery_count=count,
                worker_id=worker_id,
                lease_deadline=self.clock() + visibility_timeout,
            )
            self._inflight[msg.message_id] = delivery
            return delivery

        return None

    def ack(self, worker_id: str, message_id: str) -> bool:
        delivery = self._inflight.get(message_id)
        if delivery is None or delivery.worker_id != worker_id:
            return False
        delivery.acked = True
        self._completed_dedupe_keys.add(delivery.message.dedupe_key)
        self._inflight.pop(message_id, None)
        return True

    def nack(self, worker_id: str, message_id: str, reason: str = "nack") -> bool:
        delivery = self._inflight.get(message_id)
        if delivery is None or delivery.worker_id != worker_id:
            return False

        self._inflight.pop(message_id, None)
        msg = delivery.message

        if delivery.delivery_count >= msg.max_deliveries:
            self._dead_letters.append(
                DeadLetter(msg, delivery.delivery_count, reason)
            )
        else:
            self._queues.setdefault(msg.topic, deque()).appendleft(msg)
        return True

    def extend_lease(self, worker_id: str, message_id: str, extra_seconds: float) -> bool:
        if extra_seconds <= 0:
            raise ValueError("extra_seconds must be > 0")
        delivery = self._inflight.get(message_id)
        if delivery is None or delivery.worker_id != worker_id:
            return False
        delivery.lease_deadline += extra_seconds
        return True

    def is_completed(self, dedupe_key: str) -> bool:
        return dedupe_key in self._completed_dedupe_keys

    def dead_letters(self) -> tuple[DeadLetter, ...]:
        self._expire_leases()
        return tuple(self._dead_letters)

    def queued_count(self, topic: str) -> int:
        self._expire_leases()
        return len(self._queues.setdefault(topic, deque()))

    def inflight_count(self) -> int:
        self._expire_leases()
        return len(self._inflight)


@dataclass(frozen=True)
class WorkerConfig:
    worker_id: str
    topic: str
    visibility_timeout: float = 30.0


@dataclass
class WorkerStats:
    pulled: int = 0
    acked: int = 0
    nacked: int = 0
    failures: int = 0
    duplicates_skipped: int = 0


class Worker:
    """
    Pulls one message at a time and acks only after the handler succeeds.
    """

    def __init__(
        self,
        bus: InMemoryMessageBus,
        config: WorkerConfig,
        handler: Callable[[Message], Any],
    ) -> None:
        self.bus = bus
        self.config = config
        self.handler = handler
        self.stats = WorkerStats()

    def run_once(self) -> Any | None:
        delivery = self.bus.pull(
            self.config.topic,
            self.config.worker_id,
            self.config.visibility_timeout,
        )
        if delivery is None:
            return None

        self.stats.pulled += 1
        msg = delivery.message

        if self.bus.is_completed(msg.dedupe_key):
            self.stats.duplicates_skipped += 1
            self.bus.ack(self.config.worker_id, msg.message_id)
            return None

        try:
            result = self.handler(msg)
        except Exception:
            self.stats.failures += 1
            self.stats.nacked += 1
            self.bus.nack(
                self.config.worker_id,
                msg.message_id,
                reason="worker handler failure",
            )
            return None

        if not self.bus.ack(self.config.worker_id, msg.message_id):
            # An ack ownership failure is treated conservatively as failure.
            self.stats.failures += 1
            return None

        self.stats.acked += 1
        return result


@dataclass
class WorkerCoordinator:
    bus: InMemoryMessageBus
    workers: list[Worker] = field(default_factory=list)

    def register(self, worker: Worker) -> None:
        if any(w.config.worker_id == worker.config.worker_id for w in self.workers):
            raise ValueError(f"duplicate worker_id: {worker.config.worker_id}")
        self.workers.append(worker)

    def cycle(self) -> list[Any]:
        results: list[Any] = []
        for worker in self.workers:
            result = worker.run_once()
            if result is not None:
                results.append(result)
        return results

    def drain(self, max_cycles: int = 1000) -> list[Any]:
        if max_cycles < 1:
            raise ValueError("max_cycles must be >= 1")

        all_results: list[Any] = []
        for _ in range(max_cycles):
            before = sum(w.stats.pulled for w in self.workers)
            all_results.extend(self.cycle())
            after = sum(w.stats.pulled for w in self.workers)
            if after == before:
                break
        return all_results
