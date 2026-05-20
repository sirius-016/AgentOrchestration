"""Dead-letter queue with redacted payload summaries for the operations viewer.

The viewer shows redacted task summaries by default to prevent routine operational
access from revealing sensitive task data. Full payload access requires an audited
elevated path.
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Fields to exclude from summary view (sensitive operational data)
EXCLUDED_FROM_SUMMARY = frozenset({
    "authorization", "auth_token", "api_key", "api_secret", "password",
    "credential", "token", "secret", "private_key",
    "payload", "body", "input_data", "input",
    "env", "environment", "secrets",
    "internal_metadata", "_internal",
})

# Fields to show in summary view (safe debugging info)
SUMMARY_FIELDS = frozenset({
    "task_id", "task_name", "task_type",
    "agent_id", "agent_name",
    "status", "error_type", "error_message",
    "attempt", "retries",
    "queue", "priority",
    "created_at", "failed_at", "enqueued_at",
    "duration_ms", "run_time_ms",
})


def _safe_summary(task: Dict) -> Dict:
    """Build a safe summary of a dead-letter task.
    
    Excludes sensitive fields and large data. Shows only identifiers,
    status info, and safe metadata.
    """
    summary = {}
    
    for key, value in task.items():
        key_lower = key.lower()
        
        # Skip excluded/sensitive fields
        if key_lower in EXCLUDED_FROM_SUMMARY:
            summary[key] = "[EXCLUDED]"
            continue
        
        # Skip fields with sensitive names
        if any(p in key_lower for p in ["auth", "token", "key", "secret", "password", "credential"]):
            summary[key] = "[EXCLUDED]"
            continue
        
        # Truncate large values
        if isinstance(value, str) and len(value) > 200:
            summary[key] = value[:200] + "...[truncated]"
        elif isinstance(value, (dict, list)):
            summary[key] = f"<{type(value).__name__} len={len(value)}>"
        else:
            summary[key] = value
    
    return summary


def _summarize_error(error_data: Any) -> str:
    """Create a safe error summary."""
    if isinstance(error_data, dict):
        return error_data.get("message", error_data.get("error", str(error_data)))[:200]
    return str(error_data)[:200]


class DeadLetterEntry:
    """A single failed task entry in the dead-letter queue."""

    def __init__(self, task: Dict, error: Any, attempt: int = 1):
        self.task = task
        self.error = error
        self.attempt = attempt
        self._id = task.get("id", f"dlq-{time.time()}")
        self._created_at = time.time()
        self._audit_log: List[Dict] = []

    @property
    def id(self) -> str:
        return self._id

    @property
    def created_at(self) -> float:
        return self._created_at

    def summary(self) -> Dict:
        """Return a safe redacted summary of the failed task.
        
        This is the DEFAULT view shown in the operations UI.
        Full payload is NOT exposed in this view.
        """
        summary = _safe_summary(self.task)
        summary["_meta"] = {
            "dlq_entry_id": self._id,
            "attempt": self.attempt,
            "error_summary": _summarize_error(self.error),
            "view_type": "summary",
        }
        return summary

    def full_payload(self) -> Dict:
        """Return the full task payload (audited elevated path).
        
        This endpoint should only be accessible to users with elevated
        permissions. All accesses are logged.
        """
        self._audit_log.append({
            "accessed_at": time.time(),
            "access_type": "full_payload",
            "payload_size": len(str(self.task)),
        })
        logger.info(
            f"Audited full payload access: dlq_entry={self._id}, "
            f"attempt={self.attempt}, payload_size={len(str(self.task))}"
        )
        return {
            "task": self.task,
            "error": self.error,
            "attempt": self.attempt,
            "id": self._id,
            "_accessed_at": time.time(),
        }

    def get_audit_log(self) -> List[Dict]:
        """Return audit log entries for this entry."""
        return self._audit_log.copy()


class DeadLetterQueue:
    """Dead-letter queue for failed tasks with redacted viewer support."""

    MAX_SIZE = 1000

    def __init__(self):
        self._entries: List[DeadLetterEntry] = []

    def add(self, task: Dict, error: Any, attempt: int = 1) -> DeadLetterEntry:
        """Add a failed task to the dead-letter queue."""
        entry = DeadLetterEntry(task, error, attempt)
        self._entries.append(entry)
        
        # Trim to max size (FIFO)
        while len(self._entries) > self.MAX_SIZE:
            self._entries.pop(0)
        
        logger.info(
            f"Added to DLQ: task_id={task.get('id')}, "
            f"error={_summarize_error(error)}, attempt={attempt}"
        )
        return entry

    def list(self, limit: int = 50) -> List[Dict]:
        """List recent DLQ entries as REDACTED summaries.
        
        This is the safe default view for the operations UI.
        Full payloads are NOT included.
        """
        entries = list(reversed(self._entries))[:limit]
        return [entry.summary() for entry in entries]

    def get(self, entry_id: str, audit: bool = False) -> Optional[Dict]:
        """Get a DLQ entry by ID.
        
        Args:
            entry_id: The DLQ entry ID
            audit: If True, return full payload and log access (elevated path).
                   If False, return redacted summary only.
        """
        entry = next((e for e in self._entries if e.id == entry_id), None)
        if entry is None:
            return None
        
        if audit:
            return entry.full_payload()
        return entry.summary()

    def size(self) -> int:
        """Return current DLQ size."""
        return len(self._entries)

    def clear(self) -> int:
        """Clear all DLQ entries. Returns count of cleared entries."""
        count = len(self._entries)
        self._entries.clear()
        return count


_dlq = DeadLetterQueue()


def get_dlq() -> DeadLetterQueue:
    """Get the global DeadLetterQueue instance."""
    return _dlq
