import unittest

from nexus1000 import (
    InMemoryMessageBus,
    Message,
    Worker,
    WorkerConfig,
    WorkerCoordinator,
    NexusOrchestrator,
)


class FakeClock:
    def __init__(self):
        self.t = 0.0
    def __call__(self):
        return self.t
    def advance(self, seconds):
        self.t += seconds


def msg(mid="m1", topic="jobs", dedupe="d1", max_deliveries=3, payload=None):
    return Message(
        message_id=mid,
        topic=topic,
        payload=payload if payload is not None else {"x": 1},
        dedupe_key=dedupe,
        max_deliveries=max_deliveries,
    )


class TestBusBasics(unittest.TestCase):
    def test_publish_pull_ack(self):
        clock = FakeClock()
        bus = InMemoryMessageBus(clock)
        self.assertTrue(bus.publish(msg()))
        d = bus.pull("jobs", "w1", 10)
        self.assertIsNotNone(d)
        self.assertEqual(d.delivery_count, 1)
        self.assertTrue(bus.ack("w1", "m1"))
        self.assertEqual(bus.inflight_count(), 0)

    def test_wrong_worker_cannot_ack(self):
        clock = FakeClock()
        bus = InMemoryMessageBus(clock)
        bus.publish(msg())
        bus.pull("jobs", "w1", 10)
        self.assertFalse(bus.ack("w2", "m1"))
        self.assertEqual(bus.inflight_count(), 1)

    def test_nack_redelivers(self):
        clock = FakeClock()
        bus = InMemoryMessageBus(clock)
        bus.publish(msg())
        d1 = bus.pull("jobs", "w1", 10)
        self.assertTrue(bus.nack("w1", "m1"))
        d2 = bus.pull("jobs", "w2", 10)
        self.assertEqual(d2.delivery_count, 2)

    def test_visibility_timeout_redelivers(self):
        clock = FakeClock()
        bus = InMemoryMessageBus(clock)
        bus.publish(msg())
        bus.pull("jobs", "w1", 5)
        clock.advance(6)
        d2 = bus.pull("jobs", "w2", 5)
        self.assertIsNotNone(d2)
        self.assertEqual(d2.delivery_count, 2)
        self.assertEqual(d2.worker_id, "w2")

    def test_extend_lease_prevents_early_redelivery(self):
        clock = FakeClock()
        bus = InMemoryMessageBus(clock)
        bus.publish(msg())
        bus.pull("jobs", "w1", 5)
        self.assertTrue(bus.extend_lease("w1", "m1", 10))
        clock.advance(6)
        self.assertIsNone(bus.pull("jobs", "w2", 5))
        self.assertEqual(bus.inflight_count(), 1)

    def test_completed_dedupe_key_blocks_republish(self):
        clock = FakeClock()
        bus = InMemoryMessageBus(clock)
        bus.publish(msg())
        bus.pull("jobs", "w1", 5)
        bus.ack("w1", "m1")
        self.assertFalse(bus.publish(msg("m2", dedupe="d1")))

    def test_duplicate_queued_messages_do_not_double_complete(self):
        clock = FakeClock()
        bus = InMemoryMessageBus(clock)
        bus.publish(msg("m1", dedupe="same"))
        bus.publish(msg("m2", dedupe="same"))
        d1 = bus.pull("jobs", "w1", 5)
        self.assertTrue(bus.ack("w1", d1.message.message_id))
        self.assertIsNone(bus.pull("jobs", "w2", 5))

    def test_max_deliveries_goes_to_dlq(self):
        clock = FakeClock()
        bus = InMemoryMessageBus(clock)
        bus.publish(msg(max_deliveries=2))
        d1 = bus.pull("jobs", "w1", 5)
        bus.nack("w1", d1.message.message_id, "fail-1")
        d2 = bus.pull("jobs", "w2", 5)
        bus.nack("w2", d2.message.message_id, "fail-2")
        dlq = bus.dead_letters()
        self.assertEqual(len(dlq), 1)
        self.assertEqual(dlq[0].delivery_count, 2)

    def test_timeout_exhaustion_goes_to_dlq(self):
        clock = FakeClock()
        bus = InMemoryMessageBus(clock)
        bus.publish(msg(max_deliveries=1))
        bus.pull("jobs", "w1", 2)
        clock.advance(3)
        self.assertEqual(bus.inflight_count(), 0)
        self.assertEqual(len(bus.dead_letters()), 1)


class TestWorkers(unittest.TestCase):
    def test_successful_worker_acks(self):
        clock = FakeClock()
        bus = InMemoryMessageBus(clock)
        bus.publish(msg(payload=5))
        worker = Worker(
            bus,
            WorkerConfig("w1", "jobs", 5),
            handler=lambda m: m.payload * 2,
        )
        self.assertEqual(worker.run_once(), 10)
        self.assertEqual(worker.stats.acked, 1)
        self.assertTrue(bus.is_completed("d1"))

    def test_failed_worker_nacks(self):
        clock = FakeClock()
        bus = InMemoryMessageBus(clock)
        bus.publish(msg())

        def bad(_):
            raise ValueError("boom")

        worker = Worker(bus, WorkerConfig("w1", "jobs", 5), bad)
        self.assertIsNone(worker.run_once())
        self.assertEqual(worker.stats.failures, 1)
        self.assertEqual(worker.stats.nacked, 1)
        self.assertEqual(bus.queued_count("jobs"), 1)

    def test_two_workers_share_work(self):
        clock = FakeClock()
        bus = InMemoryMessageBus(clock)
        for i in range(4):
            bus.publish(msg(f"m{i}", dedupe=f"d{i}", payload=i))

        seen = []
        w1 = Worker(bus, WorkerConfig("w1", "jobs"), lambda m: seen.append(("w1", m.payload)) or m.payload)
        w2 = Worker(bus, WorkerConfig("w2", "jobs"), lambda m: seen.append(("w2", m.payload)) or m.payload)

        coord = WorkerCoordinator(bus)
        coord.register(w1)
        coord.register(w2)
        coord.drain()

        self.assertEqual(len(seen), 4)
        self.assertGreater(w1.stats.acked, 0)
        self.assertGreater(w2.stats.acked, 0)

    def test_duplicate_worker_id_rejected(self):
        clock = FakeClock()
        bus = InMemoryMessageBus(clock)
        coord = WorkerCoordinator(bus)
        coord.register(Worker(bus, WorkerConfig("w1", "jobs"), lambda m: 1))
        with self.assertRaises(ValueError):
            coord.register(Worker(bus, WorkerConfig("w1", "jobs"), lambda m: 1))

    def test_drain_stops_when_no_work(self):
        clock = FakeClock()
        bus = InMemoryMessageBus(clock)
        worker = Worker(bus, WorkerConfig("w1", "jobs"), lambda m: 1)
        coord = WorkerCoordinator(bus, [worker])
        out = coord.drain(max_cycles=10)
        self.assertEqual(out, [])
        self.assertEqual(worker.stats.pulled, 0)


class TestAtLeastOnceAndIdempotency(unittest.TestCase):
    def test_crashed_worker_message_is_redelivered(self):
        clock = FakeClock()
        bus = InMemoryMessageBus(clock)
        bus.publish(msg())
        d = bus.pull("jobs", "w1", 2)
        self.assertEqual(d.worker_id, "w1")
        clock.advance(3)
        d2 = bus.pull("jobs", "w2", 2)
        self.assertEqual(d2.worker_id, "w2")
        self.assertEqual(d2.delivery_count, 2)

    def test_acked_work_not_redelivered(self):
        clock = FakeClock()
        bus = InMemoryMessageBus(clock)
        bus.publish(msg())
        d = bus.pull("jobs", "w1", 2)
        bus.ack("w1", d.message.message_id)
        clock.advance(100)
        self.assertIsNone(bus.pull("jobs", "w2", 2))


class TestOrchestratorIntegration(unittest.TestCase):
    def test_orchestrator_builds_worker_coordinator(self):
        clock = FakeClock()
        orch = NexusOrchestrator()

        coord = orch.build_worker_coordinator(
            clock,
            [
                (WorkerConfig("w1", "jobs"), lambda m: m.payload),
                (WorkerConfig("w2", "jobs"), lambda m: m.payload),
            ],
        )

        coord.bus.publish(msg("m1", dedupe="d1", payload=1))
        coord.bus.publish(msg("m2", dedupe="d2", payload=2))
        results = coord.drain()

        self.assertEqual(sorted(results), [1, 2])
        self.assertIn("workers", [e.stage for e in orch.timeline.events])


if __name__ == "__main__":
    unittest.main()
