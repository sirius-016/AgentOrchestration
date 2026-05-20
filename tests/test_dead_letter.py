"""Tests for dead-letter queue redaction and audit logging (#149)."""

import pytest
import time
from src.queue.dead_letter import DeadLetterQueue, DeadLetterMessage


class TestDeadLetterMessage:
    def test_to_dict_default_redacted(self):
        """Default view should redact payload and show summary instead."""
        msg = DeadLetterMessage(
            message_id="msg-1",
            queue="default",
            payload={"secret_key": "abc123", "data": "hello"},
            error="processing failed",
            enqueued_at=time.time(),
            dead_at=time.time(),
        )
        d = msg.to_dict()
        assert "payload" not in d
        assert "payload_summary" in d
        assert "payload_digest" in d

    def test_to_dict_raw_includes_payload(self):
        """Raw view should include the full payload."""
        msg = DeadLetterMessage(
            message_id="msg-2",
            queue="default",
            payload={"key": "value"},
            error="timeout",
            enqueued_at=time.time(),
            dead_at=time.time(),
        )
        d = msg.to_dict(include_payload=True)
        assert "payload" in d
        assert d["payload"] == {"key": "value"}

    def test_sensitive_metadata_redacted(self):
        """Metadata with sensitive keys should be redacted."""
        msg = DeadLetterMessage(
            message_id="msg-3",
            queue="default",
            payload={"data": "safe"},
            error="error",
            enqueued_at=time.time(),
            dead_at=time.time(),
            metadata={"api_key": "secret123", "normal_field": "visible"},
        )
        d = msg.to_dict()
        assert d["metadata"]["api_key"] == "***REDACTED***"
        assert d["metadata"]["normal_field"] == "visible"

    def test_long_payload_truncated_in_summary(self):
        """Long payloads should be truncated in the summary view."""
        long_payload = "x" * 500
        msg = DeadLetterMessage(
            message_id="msg-4",
            queue="default",
            payload=long_payload,
            error="error",
            enqueued_at=time.time(),
            dead_at=time.time(),
        )
        d = msg.to_dict()
        assert "[REDACTED]" in d["payload_summary"]
        assert len(d["payload_summary"]) < 200

    def test_payload_digest_consistent(self):
        """Same payload should produce the same digest."""
        msg1 = DeadLetterMessage("a", "q", {"x": 1}, "e", 0, 0)
        msg2 = DeadLetterMessage("b", "q", {"x": 1}, "e", 0, 0)
        assert msg1._payload_digest() == msg2._payload_digest()


class TestDeadLetterQueue:
    def test_list_messages_redacted_by_default(self):
        """list_messages should return redacted views by default."""
        dlq = DeadLetterQueue()
        dlq.add("msg-1", "default", {"password": "secret"}, "error")
        messages = dlq.list_messages()
        assert len(messages) == 1
        assert "payload" not in messages[0]
        assert "payload_summary" in messages[0]

    def test_get_raw_message_with_audit(self):
        """Raw access should be audit-logged with actor and reason."""
        dlq = DeadLetterQueue()
        dlq.add("msg-1", "default", {"sensitive": "data"}, "error")

        result = dlq.get_raw_message("msg-1", actor="admin@example.com", reason="debugging prod issue")
        assert result is not None
        assert "payload" in result
        assert result["payload"] == {"sensitive": "data"}

        # Verify audit log
        audit = dlq.get_audit_log()
        assert len(audit) == 1
        assert audit[0]["actor"] == "admin@example.com"
        assert audit[0]["reason"] == "debugging prod issue"
        assert audit[0]["message_id"] == "msg-1"

    def test_get_raw_message_nonexistent(self):
        """Raw access for nonexistent message should return None."""
        dlq = DeadLetterQueue()
        result = dlq.get_raw_message("nonexistent", actor="admin", reason="test")
        assert result is None

    def test_audit_log_filter_by_message_id(self):
        """Audit log should be filterable by message_id."""
        dlq = DeadLetterQueue()
        dlq.add("msg-1", "default", {"data": "a"}, "error")
        dlq.add("msg-2", "default", {"data": "b"}, "error")

        dlq.get_raw_message("msg-1", actor="user1", reason="reason1")
        dlq.get_raw_message("msg-2", actor="user2", reason="reason2")

        audit = dlq.get_audit_log(message_id="msg-1")
        assert len(audit) == 1
        assert audit[0]["actor"] == "user1"

    def test_count_by_queue(self):
        """Count should support queue filtering."""
        dlq = DeadLetterQueue()
        dlq.add("msg-1", "queue-a", {"data": 1}, "error")
        dlq.add("msg-2", "queue-b", {"data": 2}, "error")
        dlq.add("msg-3", "queue-a", {"data": 3}, "error")

        assert dlq.count() == 3
        assert dlq.count(queue="queue-a") == 2
        assert dlq.count(queue="queue-b") == 1

    def test_remove_message(self):
        """Removed messages should not appear in listings."""
        dlq = DeadLetterQueue()
        dlq.add("msg-1", "default", {"data": 1}, "error")
        assert dlq.count() == 1
        assert dlq.remove("msg-1") is True
        assert dlq.count() == 0
        assert dlq.remove("msg-1") is False
