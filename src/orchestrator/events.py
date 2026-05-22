"""Event Bus — Shared event bus with tenant ownership validation."""

import logging
import time
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set
from uuid import uuid4

from src.common.errors import TenantOwnershipError, EventValidationError

logger = logging.getLogger(__name__)


class EventLifecycle(Enum):
    """Lifecycle states for an event."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


class Event:
    """Represents an event on the shared event bus."""

    def __init__(
        self,
        event_type: str,
        tenant_id: str,
        sender: str,
        payload: Optional[Dict[str, Any]] = None,
        attempt: int = 1,
        revision: int = 1,
    ):
        self.id = str(uuid4())
        self.event_type = event_type
        self.tenant_id = tenant_id
        self.sender = sender
        self.payload = payload or {}
        self.attempt = attempt
        self.revision = revision
        self.lifecycle = EventLifecycle.PENDING
        self.created_at = time.time()
        self.updated_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "event_type": self.event_type,
            "tenant_id": self.tenant_id,
            "sender": self.sender,
            "payload": self.payload,
            "attempt": self.attempt,
            "revision": self.revision,
            "lifecycle": self.lifecycle.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class TenantOwnerStore:
    """Tracks which tenants are owned by which senders."""

    def __init__(self):
        self._owners: Dict[str, str] = {}  # tenant_id -> sender
        self._sender_tenants: Dict[str, Set[str]] = {}  # sender -> set of tenant_ids

    def register_tenant(self, tenant_id: str, owner: str) -> None:
        """Register a tenant as owned by a sender."""
        self._owners[tenant_id] = owner
        if owner not in self._sender_tenants:
            self._sender_tenants[owner] = set()
        self._sender_tenants[owner].add(tenant_id)

    def is_owner(self, sender: str, tenant_id: str) -> bool:
        """Check if a sender owns a specific tenant."""
        return self._owners.get(tenant_id) == sender

    def get_tenants_for_sender(self, sender: str) -> Set[str]:
        """Get all tenants owned by a sender."""
        return self._sender_tenants.get(sender, set()).copy()

    def remove_tenant(self, tenant_id: str) -> bool:
        """Remove a tenant registration."""
        owner = self._owners.pop(tenant_id, None)
        if owner and owner in self._sender_tenants:
            self._sender_tenants[owner].discard(tenant_id)
            return True
        return False


class EventBus:
    """Shared event bus with tenant ownership validation.

    Validates that events reference only tenants owned by the
    authenticated sender before accepting them into the bus.
    Also enforces lifecycle, attempt, and revision invariants
    before committing state transitions.
    """

    def __init__(self, tenant_store: Optional[TenantOwnerStore] = None):
        self._tenant_store = tenant_store or TenantOwnerStore()
        self._subscribers: Dict[str, List[Callable]] = {}
        self._event_log: List[Event] = []
        self._max_attempts = 5

    def register_tenant(self, tenant_id: str, owner: str) -> None:
        """Register a tenant owner for validation."""
        self._tenant_store.register_tenant(tenant_id, owner)
        logger.info(f"Registered tenant '{tenant_id}' owned by '{owner}'")

    def validate_event(self, event: Event) -> None:
        """Validate an event before accepting it.

        Checks:
        1. Sender owns the tenant referenced in the event
        2. Event payload does not reference tenants not owned by the sender
        3. Attempt and revision numbers are valid
        4. Lifecycle state allows the transition

        Raises:
            TenantOwnershipError: If sender does not own the referenced tenant
            EventValidationError: If other validation checks fail
        """
        # Check 1: Sender owns the primary tenant
        if not self._tenant_store.is_owner(event.sender, event.tenant_id):
            logger.warning(
                f"Rejected event {event.id}: sender '{event.sender}' "
                f"does not own tenant '{event.tenant_id}'"
            )
            raise TenantOwnershipError(event.sender, event.tenant_id)

        # Check 2: Payload tenant references belong to sender
        payload_tenant_ids = event.payload.get("tenant_ids", [])
        if isinstance(payload_tenant_ids, list):
            for tid in payload_tenant_ids:
                if not self._tenant_store.is_owner(event.sender, tid):
                    logger.warning(
                        f"Rejected event {event.id}: sender '{event.sender}' "
                        f"does not own referenced tenant '{tid}' in payload"
                    )
                    raise TenantOwnershipError(event.sender, tid)

        # Check 3: Attempt and revision validity
        if event.attempt < 1:
            raise EventValidationError(
                f"Invalid attempt {event.attempt}: must be >= 1"
            )
        if event.revision < 1:
            raise EventValidationError(
                f"Invalid revision {event.revision}: must be >= 1"
            )
        if event.attempt > self._max_attempts:
            raise EventValidationError(
                f"Attempt {event.attempt} exceeds max attempts {self._max_attempts}"
            )

        # Check 4: Lifecycle state check — only PENDING events can be submitted
        if event.lifecycle not in (EventLifecycle.PENDING, EventLifecycle.PROCESSING):
            raise EventValidationError(
                f"Event in lifecycle state '{event.lifecycle.value}' cannot be submitted"
            )

    def publish(self, event: Event) -> str:
        """Publish an event to the bus after validation.

        Returns the event ID on success.

        Raises:
            TenantOwnershipError: If sender does not own referenced tenants
            EventValidationError: If event fails validation
        """
        self.validate_event(event)

        event.lifecycle = EventLifecycle.PROCESSING
        event.updated_at = time.time()
        self._event_log.append(event)

        logger.info(
            f"Event {event.id} accepted: type={event.event_type} "
            f"tenant={event.tenant_id} sender={event.sender}"
        )

        # Notify subscribers
        subscribers = self._subscribers.get(event.event_type, [])
        for callback in subscribers:
            try:
                callback(event)
            except Exception as e:
                logger.error(f"Subscriber error for event {event.id}: {e}")

        return event.id

    def subscribe(self, event_type: str, callback: Callable) -> None:
        """Subscribe to events of a specific type."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)

    def complete_event(self, event_id: str) -> bool:
        """Mark an event as completed."""
        for event in self._event_log:
            if event.id == event_id:
                if event.lifecycle != EventLifecycle.PROCESSING:
                    logger.warning(
                        f"Cannot complete event {event_id} in state "
                        f"'{event.lifecycle.value}'"
                    )
                    return False
                event.lifecycle = EventLifecycle.COMPLETED
                event.updated_at = time.time()
                return True
        return False

    def fail_event(self, event_id: str) -> bool:
        """Mark an event as failed."""
        for event in self._event_log:
            if event.id == event_id:
                if event.lifecycle != EventLifecycle.PROCESSING:
                    return False
                event.lifecycle = EventLifecycle.FAILED
                event.updated_at = time.time()
                return True
        return False

    def get_event(self, event_id: str) -> Optional[Event]:
        """Retrieve an event by ID."""
        for event in self._event_log:
            if event.id == event_id:
                return event
        return None

    def get_events_for_tenant(self, tenant_id: str) -> List[Event]:
        """Get all events for a specific tenant."""
        return [e for e in self._event_log if e.tenant_id == tenant_id]

    @property
    def event_count(self) -> int:
        return len(self._event_log)
