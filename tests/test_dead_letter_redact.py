"""Tests for dead-letter queue viewer redaction."""
import pytest
from src.orchestrator.dead_letter import (
    DeadLetterQueue, DeadLetterEntry,
    _safe_summary, _summarize_error,
)


def test_summary_excludes_payload():
    """Test that summary view excludes sensitive payload fields."""
    task = {
        "task_id": "task-1",
        "status": "failed",
        "payload": {"auth_token": "secret", "data": "value"},
        "authorization": "Bearer secret",
    }
    entry = DeadLetterEntry(task, "timeout error")
    
    summary = entry.summary()
    
    # Safe field preserved
    assert summary["task_id"] == "task-1"
    assert summary["status"] == "failed"
    
    # Sensitive fields excluded
    assert summary["payload"] == "[EXCLUDED]"
    assert summary["authorization"] == "[EXCLUDED]"
    
    # Full payload NOT in summary
    assert "auth_token" not in str(summary.get("_meta", {}))


def test_full_payload_is_audited():
    """Test that full payload access is logged."""
    task = {"task_id": "task-2", "secret": "my-secret"}
    entry = DeadLetterEntry(task, "error")
    
    assert len(entry.get_audit_log()) == 0
    
    entry.full_payload()
    
    assert len(entry.get_audit_log()) == 1
    assert entry.get_audit_log()[0]["access_type"] == "full_payload"


def test_dlq_list_returns_summaries():
    """Test that DLQ.list() returns only redacted summaries."""
    dlq = DeadLetterQueue()
    dlq.add({"task_id": "t1", "payload": "sensitive-data"}, "error1")
    dlq.add({"task_id": "t2", "authorization": "secret"}, "error2")
    
    listings = dlq.list()
    
    assert len(listings) == 2
    for item in listings:
        # No full payloads
        assert "sensitive-data" not in str(item)
        assert "secret" not in str(item)


def test_dlq_get_without_audit_returns_summary():
    """Test that DLQ.get(id) returns summary, not full payload."""
    dlq = DeadLetterQueue()
    entry = dlq.add({"task_id": "t3", "password": "secret-pwd"}, "err")
    
    result = dlq.get(entry.id, audit=False)
    
    assert result["task_id"] == "t3"
    assert result["password"] == "[EXCLUDED]"
    assert "full_payload" not in str(result)


def test_dlq_get_with_audit_returns_full():
    """Test that DLQ.get(id, audit=True) returns full payload."""
    dlq = DeadLetterQueue()
    entry = dlq.add({"task_id": "t4", "api_key": "secret"}, "err")
    
    result = dlq.get(entry.id, audit=True)
    
    assert result["task"]["api_key"] == "secret"
    assert result["_accessed_at"] is not None


def test_error_summarization():
    """Test that error messages are safely summarized."""
    task = {"task_id": "t5"}
    entry = DeadLetterEntry(task, {"message": "Connection timeout after 30s", "code": 500})
    
    summary = entry.summary()
    assert "Connection timeout" in summary["_meta"]["error_summary"]
    assert summary["_meta"]["error_summary"] == "Connection timeout after 30s"
