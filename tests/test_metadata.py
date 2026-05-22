"""Tests for metadata filtering to prevent internal field leakage."""

import pytest
from src.common.metadata import (
    INTERNAL_FIELDS,
    filter_internal_metadata,
    filter_payload_recursive,
    sanitize_webhook_payload,
)


class TestInternalFields:
    """Test that INTERNAL_FIELDS contains expected fields."""

    def test_internal_fields_not_empty(self):
        """Ensure INTERNAL_FIELDS is populated."""
        assert len(INTERNAL_FIELDS) > 0

    def test_expected_fields_present(self):
        """Ensure critical internal fields are in the list."""
        expected_fields = {
            "task_id",
            "attempt_id",
            "internal_state",
            "worker_id",
            "execution_id",
        }
        assert expected_fields.issubset(INTERNAL_FIELDS)


class TestFilterInternalMetadata:
    """Test filter_internal_metadata function."""

    def test_filters_task_id(self):
        """Internal task_id should be removed."""
        payload = {"task_id": "123", "status": "running", "result": "ok"}
        filtered = filter_internal_metadata(payload)
        assert "task_id" not in filtered
        assert filtered["status"] == "running"
        assert filtered["result"] == "ok"

    def test_filters_attempt_id(self):
        """Internal attempt_id should be removed."""
        payload = {"attempt_id": "456", "data": "value"}
        filtered = filter_internal_metadata(payload)
        assert "attempt_id" not in filtered
        assert filtered["data"] == "value"

    def test_filters_multiple_internal_fields(self):
        """Multiple internal fields should all be removed."""
        payload = {
            "task_id": "123",
            "attempt_id": "456",
            "worker_id": "worker-1",
            "internal_state": "secret",
            "status": "complete",
            "result": "success",
        }
        filtered = filter_internal_metadata(payload)
        assert "task_id" not in filtered
        assert "attempt_id" not in filtered
        assert "worker_id" not in filtered
        assert "internal_state" not in filtered
        assert filtered["status"] == "complete"
        assert filtered["result"] == "success"

    def test_preserves_non_internal_fields(self):
        """Non-internal fields should be preserved."""
        payload = {
            "status": "complete",
            "result": {"output": "done"},
            "metadata": {"timestamp": 1234567890},
        }
        filtered = filter_internal_metadata(payload)
        assert filtered == payload

    def test_empty_payload(self):
        """Empty payload should return empty dict."""
        assert filter_internal_metadata({}) == {}

    def test_none_payload(self):
        """None payload should return None."""
        assert filter_internal_metadata(None) is None

    def test_custom_internal_fields(self):
        """Should be able to specify custom internal fields."""
        payload = {"custom_internal": "secret", "public": "visible"}
        filtered = filter_internal_metadata(payload, internal_fields={"custom_internal"})
        assert "custom_internal" not in filtered
        assert filtered["public"] == "visible"

    def test_returns_new_dict(self):
        """Should return a new dict, not modify original."""
        payload = {"task_id": "123", "status": "ok"}
        original_copy = payload.copy()
        filtered = filter_internal_metadata(payload)
        assert payload == original_copy  # Original unchanged
        assert filtered is not payload  # Different object


class TestFilterPayloadRecursive:
    """Test filter_payload_recursive function."""

    def test_filters_nested_dict(self):
        """Should filter internal fields in nested dicts."""
        payload = {
            "task_id": "123",
            "data": {
                "attempt_id": "456",
                "value": "test"
            }
        }
        filtered = filter_payload_recursive(payload)
        assert "task_id" not in filtered
        assert "attempt_id" not in filtered["data"]
        assert filtered["data"]["value"] == "test"

    def test_filters_in_lists(self):
        """Should filter internal fields in dicts within lists."""
        payload = {
            "items": [
                {"task_id": "1", "value": "a"},
                {"task_id": "2", "value": "b"},
            ]
        }
        filtered = filter_payload_recursive(payload)
        assert "task_id" not in filtered["items"][0]
        assert "task_id" not in filtered["items"][1]
        assert filtered["items"][0]["value"] == "a"
        assert filtered["items"][1]["value"] == "b"

    def test_preserves_simple_values(self):
        """Should return simple values unchanged."""
        assert filter_payload_recursive("string") == "string"
        assert filter_payload_recursive(123) == 123
        assert filter_payload_recursive([1, 2, 3]) == [1, 2, 3]


class TestSanitizeWebhookPayload:
    """Test sanitize_webhook_payload function."""

    def test_sanitizes_task_payload(self):
        """Should sanitize a typical task webhook payload."""
        payload = {
            "event": "task.completed",
            "task_id": "internal-123",
            "data": {
                "status": "success",
                "attempt_id": "internal-456",
                "result": {"output": "done"},
            }
        }
        sanitized = sanitize_webhook_payload(payload)
        assert "task_id" not in sanitized
        assert "attempt_id" not in sanitized["data"]
        assert sanitized["event"] == "task.completed"
        assert sanitized["data"]["status"] == "success"
        assert sanitized["data"]["result"]["output"] == "done"

    def test_adds_additional_internal_fields(self):
        """Should be able to add additional fields to filter."""
        payload = {
            "custom_secret": "hidden",
            "public": "visible",
        }
        sanitized = sanitize_webhook_payload(
            payload,
            additional_internal_fields={"custom_secret"},
        )
        assert "custom_secret" not in sanitized
        assert sanitized["public"] == "visible"


class TestIntegration:
    """Integration tests for metadata filtering in webhook scenarios."""

    def test_webhook_payload_no_internal_fields(self):
        """Webhook payload should not contain any internal fields."""
        webhook_payload = {
            "event": "task.started",
            "timestamp": 1234567890,
            "data": {
                "task_id": "should-be-filtered",
                "worker_id": "should-be-filtered",
                "status": "running",
                "metadata": {
                    "internal_state": "should-be-filtered",
                    "progress": 50,
                }
            }
        }
        sanitized = sanitize_webhook_payload(webhook_payload)

        # Verify no internal fields in top level
        for field in INTERNAL_FIELDS:
            assert field not in sanitized, f"Field '{field}' should be filtered from top level"

        # Verify no internal fields in nested data
        for field in INTERNAL_FIELDS:
            assert field not in sanitized["data"], f"Field '{field}' should be filtered from data"

        # Verify non-internal fields preserved
        assert sanitized["event"] == "task.started"
        assert sanitized["data"]["status"] == "running"
        assert sanitized["data"]["metadata"]["progress"] == 50

    def test_hook_payload_filtering(self):
        """Simulate hook payload filtering as in engine.py."""
        # Simulate a task dict with internal fields
        task = {
            "id": "task-123",
            "task_id": "internal-id-456",
            "target_agent": "agent-1",
            "internal_state": "secret",
            "config": {"timeout": 300},
        }

        # Filter as done in engine.py
        filtered = filter_internal_metadata(task)

        # Verify internal fields removed
        assert "task_id" not in filtered
        assert "internal_state" not in filtered

        # Verify safe fields preserved
        assert filtered["id"] == "task-123"
        assert filtered["target_agent"] == "agent-1"
        assert filtered["config"]["timeout"] == 300
