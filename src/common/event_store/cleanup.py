"""Cleanup jobs for event stores.

This module provides separate cleanup jobs for audit records and operational logs,
ensuring that operational log cleanup never affects audit records.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from src.common.event_store.audit_store import AuditStore
from src.common.event_store.operational_log_store import OperationalLogStore

logger = logging.getLogger(__name__)


class AuditCleanupJob:
    """Cleanup job for audit records with longer retention.

    This job should be scheduled independently from operational log cleanup.
    Audit records have longer retention (default 365 days) and should only
    be cleaned up by this dedicated job.
    """

    def __init__(self, audit_store: AuditStore):
        self._store = audit_store
        self._last_run: Optional[datetime] = None
        self._records_removed = 0

    def run(self) -> int:
        """Execute audit record cleanup.

        Returns the number of expired records removed.
        """
        logger.info("Starting audit record cleanup job")
        self._last_run = datetime.utcnow()

        removed = self._store.cleanup_expired()
        self._records_removed += removed

        logger.info(f"Audit cleanup complete: removed {removed} expired records")
        return removed

    def get_stats(self) -> dict:
        """Return cleanup statistics."""
        return {
            "last_run": self._last_run.isoformat() if self._last_run else None,
            "total_records_removed": self._records_removed,
            "current_record_count": self._store.count(),
            "retention_days": self._store.get_retention_days(),
        }


class OperationalLogCleanupJob:
    """Cleanup job for operational logs with normal retention.

    This job handles both expiration-based cleanup and optional compaction.
    It is COMPLETELY SEPARATE from audit cleanup and will never affect
    audit records.
    """

    def __init__(
        self,
        log_store: OperationalLogStore,
        compact_older_than_days: Optional[int] = 7,
    ):
        self._store = log_store
        self._compact_days = compact_older_than_days
        self._last_run: Optional[datetime] = None
        self._logs_removed = 0
        self._logs_compacted = 0

    def run(self, compact: bool = True, prune_expired: bool = True) -> dict:
        """Execute operational log cleanup.

        Args:
            compact: Whether to compact older logs
            prune_expired: Whether to remove expired logs

        Returns:
            Dictionary with cleanup statistics
        """
        logger.info("Starting operational log cleanup job")
        self._last_run = datetime.utcnow()

        result = {
            "compacted": 0,
            "expired_removed": 0,
        }

        if prune_expired:
            removed = self._store.cleanup_expired()
            self._logs_removed += removed
            result["expired_removed"] = removed
            logger.info(f"Removed {removed} expired operational logs")

        if compact and self._compact_days:
            compaction = self._store.compact(older_than_days=self._compact_days)
            self._logs_compacted += compaction.get("compacted", 0)
            result["compacted"] = compaction.get("compacted", 0)
            logger.info(f"Compacted {result['compacted']} operational logs")

        logger.info("Operational log cleanup complete")
        return result

    def get_stats(self) -> dict:
        """Return cleanup statistics."""
        return {
            "last_run": self._last_run.isoformat() if self._last_run else None,
            "total_logs_removed": self._logs_removed,
            "total_logs_compacted": self._logs_compacted,
            "current_log_count": self._store.count(),
            "retention_days": self._store.get_retention_days(),
        }


class EventStoreCleanupManager:
    """Manager for coordinating separate cleanup of audit and operational stores.

    This ensures that:
    1. Audit cleanup is completely separate from operational log cleanup
    2. Audit records cannot be accidentally deleted by operational cleanup
    3. Each store has appropriate retention settings
    """

    def __init__(
        self,
        audit_store: AuditStore,
        log_store: OperationalLogStore,
    ):
        self._audit_cleanup = AuditCleanupJob(audit_store)
        self._log_cleanup = OperationalLogCleanupJob(log_store)

    def run_audit_cleanup(self) -> int:
        """Run cleanup for audit records only.

        This will NOT affect operational logs.
        """
        return self._audit_cleanup.run()

    def run_log_cleanup(self, compact: bool = True, prune_expired: bool = True) -> dict:
        """Run cleanup for operational logs only.

        This will NOT affect audit records.
        """
        return self._log_cleanup.run(compact=compact, prune_expired=prune_expired)

    def run_all(self, compact_logs: bool = True) -> dict:
        """Run both cleanup jobs in sequence.

        Returns combined statistics.
        """
        audit_removed = self.run_audit_cleanup()
        log_result = self.run_log_cleanup(compact=compact_logs)

        return {
            "audit_records_removed": audit_removed,
            "logs_removed": log_result["expired_removed"],
            "logs_compacted": log_result["compacted"],
        }

    def get_stats(self) -> dict:
        """Return combined statistics."""
        return {
            "audit": self._audit_cleanup.get_stats(),
            "operational_logs": self._log_cleanup.get_stats(),
        }
