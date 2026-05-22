"""Tests for event tenant ownership validation — Issue #1870."""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.common.errors import TenantOwnershipError, EventValidationError
from src.orchestrator.events import (
    EventBus,
    Event,
    EventLifecycle,
    TenantOwnerStore,
)
from src.orchestrator.engine import OrchestrationEngine


class TestTenantOwnerStore(unittest.TestCase):
    def setUp(self):
        self.store = TenantOwnerStore()
        self.store.register_tenant("tenant-A", "sender-1")
        self.store.register_tenant("tenant-B", "sender-1")
        self.store.register_tenant("tenant-C", "sender-2")

    def test_is_owner_positive(self):
        self.assertTrue(self.store.is_owner("sender-1", "tenant-A"))
        self.assertTrue(self.store.is_owner("sender-1", "tenant-B"))
        self.assertTrue(self.store.is_owner("sender-2", "tenant-C"))

    def test_is_owner_negative(self):
        self.assertFalse(self.store.is_owner("sender-2", "tenant-A"))
        self.assertFalse(self.store.is_owner("sender-1", "tenant-C"))
        self.assertFalse(self.store.is_owner("sender-unknown", "tenant-A"))

    def test_get_tenants_for_sender(self):
        self.assertEqual(self.store.get_tenants_for_sender("sender-1"), {"tenant-A", "tenant-B"})
        self.assertEqual(self.store.get_tenants_for_sender("sender-2"), {"tenant-C"})
        self.assertEqual(self.store.get_tenants_for_sender("sender-unknown"), set())

    def test_remove_tenant(self):
        self.assertTrue(self.store.remove_tenant("tenant-A"))
        self.assertFalse(self.store.is_owner("sender-1", "tenant-A"))
        self.assertFalse(self.store.remove_tenant("tenant-A"))


class TestEventBusTenantValidation(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus()
        self.bus.register_tenant("tenant-A", "sender-1")
        self.bus.register_tenant("tenant-B", "sender-2")

    def test_publish_valid_event(self):
        event = Event(
            event_type="task.started",
            tenant_id="tenant-A",
            sender="sender-1",
            payload={"key": "value"},
        )
        event_id = self.bus.publish(event)
        self.assertIsNotNone(event_id)
        stored = self.bus.get_event(event_id)
        self.assertEqual(stored.lifecycle, EventLifecycle.PROCESSING)

    def test_reject_event_wrong_tenant_owner(self):
        """Core issue #1870: events referencing tenants not owned by sender must be rejected."""
        event = Event(
            event_type="task.started",
            tenant_id="tenant-A",
            sender="sender-2",  # sender-2 does NOT own tenant-A
        )
        with self.assertRaises(TenantOwnershipError) as ctx:
            self.bus.publish(event)
        self.assertIn("sender-2", str(ctx.exception))
        self.assertIn("tenant-A", str(ctx.exception))

    def test_reject_event_unregistered_tenant(self):
        event = Event(
            event_type="task.started",
            tenant_id="tenant-UNKNOWN",
            sender="sender-1",
        )
        with self.assertRaises(TenantOwnershipError):
            self.bus.publish(event)

    def test_reject_payload_tenant_reference_not_owned(self):
        """Payload referencing tenant not owned by sender should be rejected."""
        event = Event(
            event_type="workflow.transition",
            tenant_id="tenant-A",
            sender="sender-1",
            payload={"tenant_ids": ["tenant-B"]},  # tenant-B owned by sender-2
        )
        with self.assertRaises(TenantOwnershipError) as ctx:
            self.bus.publish(event)
        self.assertIn("tenant-B", str(ctx.exception))

    def test_accept_payload_tenant_reference_owned(self):
        event = Event(
            event_type="workflow.transition",
            tenant_id="tenant-A",
            sender="sender-1",
            payload={"tenant_ids": ["tenant-A"]},
        )
        event_id = self.bus.publish(event)
        self.assertIsNotNone(event_id)

    def test_reject_invalid_attempt(self):
        event = Event(
            event_type="task.started",
            tenant_id="tenant-A",
            sender="sender-1",
            attempt=0,
        )
        with self.assertRaises(EventValidationError):
            self.bus.publish(event)

    def test_reject_invalid_revision(self):
        event = Event(
            event_type="task.started",
            tenant_id="tenant-A",
            sender="sender-1",
            revision=0,
        )
        with self.assertRaises(EventValidationError):
            self.bus.publish(event)

    def test_reject_completed_lifecycle_event(self):
        event = Event(
            event_type="task.started",
            tenant_id="tenant-A",
            sender="sender-1",
        )
        event.lifecycle = EventLifecycle.COMPLETED
        with self.assertRaises(EventValidationError):
            self.bus.publish(event)

    def test_reject_failed_lifecycle_event(self):
        event = Event(
            event_type="task.started",
            tenant_id="tenant-A",
            sender="sender-1",
        )
        event.lifecycle = EventLifecycle.FAILED
        with self.assertRaises(EventValidationError):
            self.bus.publish(event)

    def test_accept_pending_lifecycle_event(self):
        event = Event(
            event_type="task.started",
            tenant_id="tenant-A",
            sender="sender-1",
        )
        # PENDING is the default
        self.assertEqual(event.lifecycle, EventLifecycle.PENDING)
        event_id = self.bus.publish(event)
        self.assertIsNotNone(event_id)

    def test_event_not_stored_after_rejection(self):
        event = Event(
            event_type="task.started",
            tenant_id="tenant-A",
            sender="sender-2",
        )
        with self.assertRaises(TenantOwnershipError):
            self.bus.publish(event)
        self.assertEqual(self.bus.event_count, 0)

    def test_valid_events_are_stored(self):
        self.bus.publish(Event("t1", "tenant-A", "sender-1"))
        self.bus.publish(Event("t2", "tenant-B", "sender-2"))
        self.assertEqual(self.bus.event_count, 2)

    def test_complete_event(self):
        event_id = self.bus.publish(Event("t1", "tenant-A", "sender-1"))
        self.assertTrue(self.bus.complete_event(event_id))
        self.assertEqual(self.bus.get_event(event_id).lifecycle, EventLifecycle.COMPLETED)

    def test_fail_event(self):
        event_id = self.bus.publish(Event("t1", "tenant-A", "sender-1"))
        self.assertTrue(self.bus.fail_event(event_id))
        self.assertEqual(self.bus.get_event(event_id).lifecycle, EventLifecycle.FAILED)

    def test_duplicate_event_same_tenant_same_sender_accepted(self):
        """Stale/duplicate events from the same owner should pass tenant check."""
        e1 = Event("task.started", "tenant-A", "sender-1", attempt=1, revision=1)
        e2 = Event("task.started", "tenant-A", "sender-1", attempt=2, revision=1)
        self.bus.publish(e1)
        self.bus.publish(e2)
        self.assertEqual(self.bus.event_count, 2)


class TestOrchestrationEngineTenantIntegration(unittest.TestCase):
    def setUp(self):
        self.engine = OrchestrationEngine()
        self.engine.register_tenant("tenant-X", "owner-A")
        self.engine.register_tenant("tenant-Y", "owner-B")

    def test_engine_publish_valid_event(self):
        event = Event("agent.started", "tenant-X", "owner-A")
        event_id = self.engine.publish_event(event)
        self.assertIsNotNone(event_id)

    def test_engine_reject_invalid_tenant(self):
        event = Event("agent.started", "tenant-X", "owner-B")
        with self.assertRaises(TenantOwnershipError):
            self.engine.publish_event(event)

    def test_engine_reject_payload_cross_tenant(self):
        event = Event(
            "workflow.transition",
            "tenant-X",
            "owner-A",
            payload={"tenant_ids": ["tenant-Y"]},
        )
        with self.assertRaises(TenantOwnershipError):
            self.engine.publish_event(event)


class TestSharedEventBusInvariant(unittest.TestCase):
    """Deterministic regression test for the shared event bus trigger.

    Verifies that when a sender attempts to emit events referencing
    tenants they do not own, the orchestrator rejects the transition
    and preserves the expected lifecycle state.
    """

    def test_cross_tenant_events_rejected_lifecycle_preserved(self):
        bus = EventBus()
        bus.register_tenant("t1", "s1")
        bus.register_tenant("t2", "s2")

        # s1 publishes a valid event on t1
        valid = Event("task.created", "t1", "s1")
        valid_id = bus.publish(valid)

        # s2 attempts to publish event on t1 (not owned)
        invalid = Event("task.updated", "t1", "s2")
        with self.assertRaises(TenantOwnershipError):
            bus.publish(invalid)

        # The valid event's lifecycle is preserved
        stored = bus.get_event(valid_id)
        self.assertEqual(stored.lifecycle, EventLifecycle.PROCESSING)

        # Only the valid event is stored
        self.assertEqual(bus.event_count, 1)
        self.assertEqual(len(bus.get_events_for_tenant("t1")), 1)

    def test_stale_duplicate_event_rejected_if_lifecycle_not_pending(self):
        """Stale/duplicate event with non-pending lifecycle should be rejected."""
        bus = EventBus()
        bus.register_tenant("t1", "s1")

        event = Event("task.created", "t1", "s1")
        event_id = bus.publish(event)
        bus.complete_event(event_id)

        # Try to resubmit the completed event — lifecycle is COMPLETED
        with self.assertRaises(EventValidationError):
            bus.publish(event)


if __name__ == "__main__":
    unittest.main()
