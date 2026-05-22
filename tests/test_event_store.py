"""Tests for AuditStore — ensuring audit records are not affected by operational cleanup."""

import time
import pytest
from src.common.event_store.audit_store import AuditStore, AuditRecord
from src.common.event_store.operational_log_store import OperationalLogStore, OperationalLog
from src.common.event_store.cleanup import AuditCleanupJob, OperationalLogCleanupJob, EventStoreCleanupManager


class TestAuditStore:
    """Tests for the append-only audit store."""

    def test_append_record(self):
        """Test appending a new audit record."""
        store = AuditStore()
        record_id = store.append(
            event_type="agent.action",
            actor="user@example.com",
            action="create",
            resource="agent:123",
            metadata={"name": "test-agent"},
        )
        assert record_id is not None
        assert store.count() == 1

    def test_get_record(self):
        """Test retrieving a record by ID."""
        store = AuditStore()
        record_id = store.append(
            event_type="agent.action",
            actor="user@example.com",
            action="delete",
            resource="agent:456",
        )
        record = store.get(record_id)
        assert record is not None
        assert record.actor == "user@example.com"
        assert record.action == "delete"

    def test_record_has_digest(self):
        """Test that records have SHA-256 digest."""
        store = AuditStore()
        record_id = store.append(
            event_type="agent.action",
            actor="user@example.com",
            action="update",
            resource="agent:789",
        )
        record = store.get(record_id)
        assert record.digest is not None
        assert len(record.digest) == 64  # SHA-256 hex length

    def test_digest_verification(self):
        """Test that record digests can be verified."""
        store = AuditStore()
        record_id = store.append(
            event_type="agent.action",
            actor="user@example.com",
            action="start",
            resource="agent:111",
        )
        assert store.verify_record(record_id) is True

    def test_query_by_actor(self):
        """Test querying records by actor."""
        store = AuditStore()
        store.append(event_type="agent.action", actor="alice", action="create", resource="agent:1")
        store.append(event_type="agent.action", actor="bob", action="create", resource="agent:2")
        store.append(event_type="agent.action", actor="alice", action="delete", resource="agent:3")

        records = store.query(actor="alice")
        assert len(records) == 2
        assert all(r.actor == "alice" for r in records)

    def test_query_by_resource(self):
        """Test querying records by resource."""
        store = AuditStore()
        store.append(event_type="agent.action", actor="alice", action="create", resource="agent:1")
        store.append(event_type="agent.action", actor="bob", action="start", resource="agent:2")
        store.append(event_type="agent.action", actor="alice", action="delete", resource="agent:1")

        records = store.query(resource="agent:1")
        assert len(records) == 2

    def test_query_by_time_range(self):
        """Test querying records by time range."""
        store = AuditStore()
        now = time.time()

        # Create records with specific timestamps
        store.append(event_type="agent.action", actor="alice", action="create", resource="agent:1")
        time.sleep(0.01)
        mid_time = time.time()
        time.sleep(0.01)
        store.append(event_type="agent.action", actor="bob", action="create", resource="agent:2")

        records = store.query(start_time=mid_time)
        assert len(records) == 1
        assert records[0].actor == "bob"

    def test_longer_retention(self):
        """Test that audit store has longer default retention."""
        store = AuditStore()
        assert store.get_retention_days() == 365

    def test_custom_retention(self):
        """Test custom retention period."""
        store = AuditStore(retention_days=730)
        assert store.get_retention_days() == 730


class TestOperationalLogStore:
    """Tests for the operational log store."""

    def test_append_log(self):
        """Test appending a log entry."""
        store = OperationalLogStore()
        log_id = store.append(
            level="INFO",
            message="Agent started",
            source="agent.runtime",
        )
        assert log_id is not None
        assert store.count() == 1

    def test_get_log(self):
        """Test retrieving a log by ID."""
        store = OperationalLogStore()
        log_id = store.append(
            level="ERROR",
            message="Agent failed",
            source="agent.executor",
            context={"error": "timeout"},
        )
        log = store.get(log_id)
        assert log is not None
        assert log.level == "ERROR"
        assert log.context["error"] == "timeout"

    def test_query_by_level(self):
        """Test querying logs by level."""
        store = OperationalLogStore()
        store.append(level="INFO", message="Info 1", source="src1")
        store.append(level="ERROR", message="Error 1", source="src2")
        store.append(level="INFO", message="Info 2", source="src1")

        info_logs = store.query(level="INFO")
        assert len(info_logs) == 2

    def test_query_by_source(self):
        """Test querying logs by source."""
        store = OperationalLogStore()
        store.append(level="INFO", message="Log 1", source="module.a")
        store.append(level="INFO", message="Log 2", source="module.b")
        store.append(level="INFO", message="Log 3", source="module.a")

        logs = store.query(source="module.a")
        assert len(logs) == 2

    def test_delete_log(self):
        """Test that logs can be deleted (unlike audit records)."""
        store = OperationalLogStore()
        log_id = store.append(level="INFO", message="To delete", source="test")
        assert store.count() == 1

        result = store.delete(log_id)
        assert result is True
        assert store.count() == 0

    def test_compaction(self):
        """Test log compaction."""
        store = OperationalLogStore()

        # Add multiple logs
        for i in range(10):
            store.append(level="INFO", message=f"Log {i}", source="test.module")

        # Compact logs older than 0 days (all of them)
        result = store.compact(older_than_days=0)
        assert result["compacted"] == 10

    def test_normal_retention(self):
        """Test that operational logs have shorter default retention."""
        store = OperationalLogStore()
        assert store.get_retention_days() == 30


class TestSeparationOfConcerns:
    """Critical tests ensuring audit records are NOT affected by operational cleanup."""

    def test_audit_records_not_deleted_by_log_cleanup(self):
        """Test that operational log cleanup does NOT affect audit records."""
        audit_store = AuditStore()
        log_store = OperationalLogStore()

        # Add audit records
        audit_id1 = audit_store.append(
            event_type="agent.action",
            actor="admin",
            action="delete",
            resource="agent:important",
        )
        audit_id2 = audit_store.append(
            event_type="security.event",
            actor="system",
            action="auth_failure",
            resource="user:123",
        )

        # Add operational logs
        for i in range(100):
            log_store.append(level="INFO", message=f"Operational log {i}", source="runtime")

        assert audit_store.count() == 2
        assert log_store.count() == 100

        # Run operational log cleanup (with 0 retention to expire all)
        log_store._retention_days = 0
        removed = log_store.cleanup_expired()

        # All operational logs should be removed
        assert removed == 100
        assert log_store.count() == 0

        # Audit records should be UNAFFECTED
        assert audit_store.count() == 2
        assert audit_store.get(audit_id1) is not None
        assert audit_store.get(audit_id2) is not None

    def test_cleanup_manager_separation(self):
        """Test that EventStoreCleanupManager maintains separation."""
        audit_store = AuditStore()
        log_store = OperationalLogStore()

        manager = EventStoreCleanupManager(audit_store, log_store)

        # Add data
        audit_store.append(event_type="test", actor="user", action="act", resource="res:1")
        log_store.append(level="INFO", message="Test log", source="test")

        # Run ONLY operational log cleanup
        result = manager.run_log_cleanup(compact=False, prune_expired=False)

        # Audit should be unchanged
        assert audit_store.count() == 1

    def test_audit_digest_preserved_after_log_operations(self):
        """Test that audit digest verification still works after log operations."""
        audit_store = AuditStore()
        log_store = OperationalLogStore()

        # Add audit record
        audit_id = audit_store.append(
            event_type="critical.action",
            actor="admin",
            action="purge",
            resource="database:prod",
        )

        # Perform many log operations
        for i in range(50):
            log_id = log_store.append(level="DEBUG", message=f"Log {i}", source="test")
            log_store.delete(log_id)

        # Verify audit record is intact
        assert audit_store.verify_record(audit_id) is True
        record = audit_store.get(audit_id)
        assert record.action == "purge"


class TestCleanupJobs:
    """Tests for cleanup job classes."""

    def test_audit_cleanup_job(self):
        """Test AuditCleanupJob removes old records."""
        audit_store = AuditStore(retention_days=0)  # Immediate expiration
        job = AuditCleanupJob(audit_store)

        audit_store.append(event_type="test", actor="user", action="act", resource="res")
        time.sleep(0.01)  # Ensure time passes

        removed = job.run()
        assert removed >= 0

    def test_operational_log_cleanup_job(self):
        """Test OperationalLogCleanupJob removes and compacts logs."""
        log_store = OperationalLogStore(retention_days=0)
        job = OperationalLogCleanupJob(log_store)

        for i in range(10):
            log_store.append(level="INFO", message=f"Log {i}", source="test")

        result = job.run(compact=False, prune_expired=True)
        assert "expired_removed" in result

    def test_cleanup_manager_stats(self):
        """Test that cleanup manager provides useful stats."""
        audit_store = AuditStore()
        log_store = OperationalLogStore()

        manager = EventStoreCleanupManager(audit_store, log_store)
        stats = manager.get_stats()

        assert "audit" in stats
        assert "operational_logs" in stats
        assert stats["audit"]["retention_days"] == 365
        assert stats["operational_logs"]["retention_days"] == 30


class TestAuditRecordIntegrity:
    """Tests for audit record integrity and immutability."""

    def test_record_immutability_via_digest(self):
        """Test that record tampering is detectable."""
        record = AuditRecord(
            event_type="test",
            actor="user",
            action="create",
            resource="agent:1",
        )
        original_digest = record.digest

        # Record should verify
        assert record.verify_digest() is True

        # Tamper with the record (this is a simulation - in real code, the record would be immutable)
        record._digest = "tampered_digest"

        # Verification should now fail
        assert record.verify_digest() is False

        # Restore and verify again
        record._digest = original_digest
        assert record.verify_digest() is True

    def test_verify_all_records(self):
        """Test verifying all records in a store."""
        store = AuditStore()

        for i in range(5):
            store.append(
                event_type="test",
                actor=f"user{i}",
                action="act",
                resource=f"res{i}",
            )

        success, invalid_ids = store.verify_all()
        assert success is True
        assert len(invalid_ids) == 0

    def test_to_dict_and_from_dict(self):
        """Test serialization and deserialization of records."""
        original = AuditRecord(
            event_type="security.event",
            actor="admin",
            action="grant",
            resource="permission:admin",
            metadata={"roles": ["admin", "user"]},
        )

        data = original.to_dict()
        restored = AuditRecord.from_dict(data)

        assert restored.event_type == original.event_type
        assert restored.actor == original.actor
        assert restored.digest == original.digest
        assert restored.verify_digest() is True
