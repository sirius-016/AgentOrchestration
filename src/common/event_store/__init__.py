"""Event storage module for audit and operational logging.

This module provides separate storage for audit records and operational logs,
ensuring that audit trails cannot be accidentally pruned by operational cleanup.
"""

from src.common.event_store.audit_store import AuditStore, AuditRecord
from src.common.event_store.operational_log_store import OperationalLogStore, OperationalLog

__all__ = [
    "AuditStore",
    "AuditRecord",
    "OperationalLogStore",
    "OperationalLog",
]
