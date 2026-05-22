"""Audit Store — Append-only audit trail with digest verification.

Audit records are immutable and have longer retention than operational logs.
They cannot be pruned by operational cleanup jobs.
"""

import hashlib
import json
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple


class AuditRecord:
    """Immutable audit record with SHA-256 digest."""

    def __init__(
        self,
        event_type: str,
        actor: str,
        action: str,
        resource: str,
        metadata: Optional[Dict[str, Any]] = None,
        timestamp: Optional[float] = None,
        record_id: Optional[str] = None,
    ):
        self.id = record_id or str(uuid.uuid4())
        self.event_type = event_type
        self.actor = actor
        self.action = action
        self.resource = resource
        self.metadata = metadata or {}
        self.timestamp = timestamp or time.time()
        self._digest = self._compute_digest()

    def _compute_digest(self) -> str:
        """Compute SHA-256 digest for integrity verification."""
        payload = json.dumps({
            "id": self.id,
            "event_type": self.event_type,
            "actor": self.actor,
            "action": self.action,
            "resource": self.resource,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()

    @property
    def digest(self) -> str:
        return self._digest

    def verify_digest(self) -> bool:
        """Verify the record's integrity by recomputing digest."""
        return self._compute_digest() == self._digest

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "event_type": self.event_type,
            "actor": self.actor,
            "action": self.action,
            "resource": self.resource,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
            "digest": self._digest,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AuditRecord":
        record = cls(
            event_type=data["event_type"],
            actor=data["actor"],
            action=data["action"],
            resource=data["resource"],
            metadata=data.get("metadata"),
            timestamp=data.get("timestamp"),
            record_id=data.get("id"),
        )
        # Preserve the original digest
        record._digest = data.get("digest", record._digest)
        return record


class AuditStore:
    """Append-only store for audit records.

    Features:
    - Append-only: records cannot be modified or deleted by normal operations
    - Longer retention: default 365 days vs 30 days for operational logs
    - Digest verification: SHA-256 checksum for integrity
    - Query by actor, resource, event type, time range
    """

    DEFAULT_RETENTION_DAYS = 365

    def __init__(self, retention_days: Optional[int] = None):
        self._records: Dict[str, AuditRecord] = {}
        self._by_actor: Dict[str, List[str]] = {}
        self._by_resource: Dict[str, List[str]] = {}
        self._by_event_type: Dict[str, List[str]] = {}
        self._retention_days = retention_days or self.DEFAULT_RETENTION_DAYS

    def append(
        self,
        event_type: str,
        actor: str,
        action: str,
        resource: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Append a new audit record. Returns record ID."""
        record = AuditRecord(
            event_type=event_type,
            actor=actor,
            action=action,
            resource=resource,
            metadata=metadata,
        )
        record_id = record.id

        # Store the record
        self._records[record_id] = record

        # Update indices
        if actor not in self._by_actor:
            self._by_actor[actor] = []
        self._by_actor[actor].append(record_id)

        if resource not in self._by_resource:
            self._by_resource[resource] = []
        self._by_resource[resource].append(record_id)

        if event_type not in self._by_event_type:
            self._by_event_type[event_type] = []
        self._by_event_type[event_type].append(record_id)

        return record_id

    def get(self, record_id: str) -> Optional[AuditRecord]:
        """Get an audit record by ID."""
        return self._records.get(record_id)

    def query(
        self,
        actor: Optional[str] = None,
        resource: Optional[str] = None,
        event_type: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        limit: int = 100,
    ) -> List[AuditRecord]:
        """Query audit records by various filters."""
        # Start with all record IDs
        candidate_ids = set(self._records.keys())

        # Apply filters
        if actor:
            candidate_ids &= set(self._by_actor.get(actor, []))
        if resource:
            candidate_ids &= set(self._by_resource.get(resource, []))
        if event_type:
            candidate_ids &= set(self._by_event_type.get(event_type, []))

        # Fetch records and apply time filters
        records = []
        for rid in candidate_ids:
            record = self._records[rid]
            if start_time and record.timestamp < start_time:
                continue
            if end_time and record.timestamp > end_time:
                continue
            records.append(record)

        # Sort by timestamp descending and limit
        records.sort(key=lambda r: r.timestamp, reverse=True)
        return records[:limit]

    def verify_record(self, record_id: str) -> bool:
        """Verify a record's integrity by checking its digest."""
        record = self._records.get(record_id)
        if not record:
            return False
        return record.verify_digest()

    def verify_all(self) -> Tuple[bool, List[str]]:
        """Verify all records. Returns (success, list of invalid record IDs)."""
        invalid_ids = []
        for record_id, record in self._records.items():
            if not record.verify_digest():
                invalid_ids.append(record_id)
        return len(invalid_ids) == 0, invalid_ids

    def count(self) -> int:
        """Return total number of audit records."""
        return len(self._records)

    def cleanup_expired(self) -> int:
        """Remove records older than retention period.

        This is a controlled cleanup that respects the longer audit retention.
        Returns number of records removed.

        Note: This method should only be called by dedicated audit cleanup jobs,
        NOT by operational log cleanup.
        """
        cutoff = time.time() - (self._retention_days * 86400)
        expired_ids = [
            rid for rid, record in self._records.items()
            if record.timestamp < cutoff
        ]

        for rid in expired_ids:
            record = self._records.pop(rid)
            # Clean up indices
            if record.actor in self._by_actor:
                self._by_actor[record.actor] = [
                    x for x in self._by_actor[record.actor] if x != rid
                ]
            if record.resource in self._by_resource:
                self._by_resource[record.resource] = [
                    x for x in self._by_resource[record.resource] if x != rid
                ]
            if record.event_type in self._by_event_type:
                self._by_event_type[record.event_type] = [
                    x for x in self._by_event_type[record.event_type] if x != rid
                ]

        return len(expired_ids)

    def get_retention_days(self) -> int:
        """Return current retention period in days."""
        return self._retention_days
