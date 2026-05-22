"""Operational Log Store — Mutable operational logs with normal retention.

Operational logs can be compacted, pruned, and have shorter retention.
These are separate from audit records and can be safely cleaned up
without affecting audit trails.
"""

import json
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional


class OperationalLog:
    """Operational log entry for runtime events."""

    def __init__(
        self,
        level: str,
        message: str,
        source: str,
        context: Optional[Dict[str, Any]] = None,
        timestamp: Optional[float] = None,
        log_id: Optional[str] = None,
    ):
        self.id = log_id or str(uuid.uuid4())
        self.level = level.upper()
        self.message = message
        self.source = source
        self.context = context or {}
        self.timestamp = timestamp or time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "level": self.level,
            "message": self.message,
            "source": self.source,
            "context": self.context,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OperationalLog":
        return cls(
            level=data["level"],
            message=data["message"],
            source=data["source"],
            context=data.get("context"),
            timestamp=data.get("timestamp"),
            log_id=data.get("id"),
        )


class OperationalLogStore:
    """Store for operational logs with compaction support.

    Features:
    - Normal retention: default 30 days (vs 365 for audit)
    - Can be compacted: older logs can be aggregated or summarized
    - Can be pruned: logs can be deleted during cleanup
    - Query by level, source, time range

    Note: This store is completely separate from AuditStore.
    Cleanup of operational logs does NOT affect audit records.
    """

    DEFAULT_RETENTION_DAYS = 30

    def __init__(self, retention_days: Optional[int] = None):
        self._logs: Dict[str, OperationalLog] = {}
        self._by_level: Dict[str, List[str]] = {}
        self._by_source: Dict[str, List[str]] = {}
        self._retention_days = retention_days or self.DEFAULT_RETENTION_DAYS

    def append(
        self,
        level: str,
        message: str,
        source: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Append a new operational log entry. Returns log ID."""
        log = OperationalLog(
            level=level,
            message=message,
            source=source,
            context=context,
        )
        log_id = log.id

        # Store the log
        self._logs[log_id] = log

        # Update indices
        level_key = log.level
        if level_key not in self._by_level:
            self._by_level[level_key] = []
        self._by_level[level_key].append(log_id)

        if source not in self._by_source:
            self._by_source[source] = []
        self._by_source[source].append(log_id)

        return log_id

    def get(self, log_id: str) -> Optional[OperationalLog]:
        """Get a log entry by ID."""
        return self._logs.get(log_id)

    def query(
        self,
        level: Optional[str] = None,
        source: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        message_contains: Optional[str] = None,
        limit: int = 100,
    ) -> List[OperationalLog]:
        """Query operational logs by various filters."""
        # Start with all log IDs
        candidate_ids = set(self._logs.keys())

        # Apply filters
        if level:
            level = level.upper()
            candidate_ids &= set(self._by_level.get(level, []))
        if source:
            candidate_ids &= set(self._by_source.get(source, []))

        # Fetch logs and apply time/message filters
        logs = []
        for lid in candidate_ids:
            log = self._logs[lid]
            if start_time and log.timestamp < start_time:
                continue
            if end_time and log.timestamp > end_time:
                continue
            if message_contains and message_contains.lower() not in log.message.lower():
                continue
            logs.append(log)

        # Sort by timestamp descending and limit
        logs.sort(key=lambda l: l.timestamp, reverse=True)
        return logs[:limit]

    def delete(self, log_id: str) -> bool:
        """Delete a specific log entry.

        Note: This is allowed for operational logs, unlike audit records.
        """
        log = self._logs.pop(log_id, None)
        if not log:
            return False

        # Clean up indices
        level_key = log.level
        if level_key in self._by_level:
            self._by_level[level_key] = [
                x for x in self._by_level[level_key] if x != log_id
            ]
        if log.source in self._by_source:
            self._by_source[log.source] = [
                x for x in self._by_source[log.source] if x != log_id
            ]

        return True

    def compact(self, older_than_days: int = 7) -> Dict[str, Any]:
        """Compact older logs by aggregating them into summaries.

        This reduces storage while preserving useful information.
        Returns compaction statistics.
        """
        cutoff = time.time() - (older_than_days * 86400)
        to_compact = [
            log for log in self._logs.values()
            if log.timestamp < cutoff
        ]

        if not to_compact:
            return {"compacted": 0, "summary": None}

        # Group by level and source
        grouped: Dict[str, List[OperationalLog]] = {}
        for log in to_compact:
            key = f"{log.level}:{log.source}"
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(log)

        # Create summaries
        summaries = []
        for key, logs in grouped.items():
            level, source = key.split(":", 1)
            summaries.append({
                "level": level,
                "source": source,
                "count": len(logs),
                "oldest": min(l.timestamp for l in logs),
                "newest": max(l.timestamp for l in logs),
            })

            # Remove compacted logs
            for log in logs:
                self.delete(log.id)

        # Add summary log entry
        summary_context = {
            "compaction": True,
            "summaries": summaries,
            "compacted_at": time.time(),
        }
        self.append(
            level="INFO",
            message=f"Compacted {len(to_compact)} log entries",
            source="log_compactor",
            context=summary_context,
        )

        return {
            "compacted": len(to_compact),
            "summaries": summaries,
        }

    def count(self) -> int:
        """Return total number of log entries."""
        return len(self._logs)

    def cleanup_expired(self) -> int:
        """Remove logs older than retention period.

        This is safe and does NOT affect audit records.
        Returns number of logs removed.
        """
        cutoff = time.time() - (self._retention_days * 86400)
        expired_ids = [
            lid for lid, log in self._logs.items()
            if log.timestamp < cutoff
        ]

        for lid in expired_ids:
            self.delete(lid)

        return len(expired_ids)

    def get_retention_days(self) -> int:
        """Return current retention period in days."""
        return self._retention_days
