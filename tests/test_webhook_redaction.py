"""Tests for webhook payload redaction."""
import pytest
from src.sdk.webhook import (
    redact_payload, redact_payload_excerpt,
    SENSITIVE_FIELDS, WebhookSubscription, WebhookDelivery,
)


def test_authorization_header_redacted():
    """Test that authorization headers are redacted."""
    payload = {"event": "task.completed", "authorization": "Bearer secret-token-123"}
    result = redact_payload(payload)
    assert result["event"] == "task.completed"
    assert result["authorization"] == "[REDACTED]"


def test_nested_sensitive_fields_redacted():
    """Test that nested sensitive fields are redacted."""
    payload = {
        "event": "run.started",
        "data": {
            "run_id": "run-123",
            "internal_metadata": {"debug_token": "secret"},
            "api_key": "sk-abc",
        },
    }
    result = redact_payload(payload)
    assert result["data"]["run_id"] == "run-123"
    assert result["data"]["internal_metadata"] == "[REDACTED]"
    assert result["data"]["api_key"] == "[REDACTED]"


def test_array_sensitive_fields_redacted():
    """Test that sensitive fields in arrays are redacted."""
    payload = {
        "event": "batch.completed",
        "results": [
            {"auth_token": "tok1"},
            {"normal_field": "value"},
            {"api_secret": "supersecret"},
        ],
    }
    result = redact_payload(payload)
    assert result["results"][0]["auth_token"] == "[REDACTED]"
    assert result["results"][1]["normal_field"] == "value"
    assert result["results"][2]["api_secret"] == "[REDACTED]"


def test_safe_fields_preserved():
    """Test that explicitly safe fields are preserved."""
    payload = {
        "event": "task.failed",
        "status": "failed",
        "agent_id": "agent-1",
        "task_id": "task-42",
    }
    result = redact_payload(payload)
    assert result == payload


def test_unknown_fields_preserved():
    """Test that unknown primitive fields are preserved."""
    payload = {"custom_field": "custom_value", "count": 42}
    result = redact_payload(payload)
    assert result["custom_field"] == "custom_value"
    assert result["count"] == 42


def test_redact_payload_excerpt_truncates():
    """Test that excerpt truncates long payloads."""
    payload = {"event": "test", "data": "x" * 500}
    result = redact_payload_excerpt(payload, max_len=50)
    assert "[REDACTED]" in result
    assert result.endswith("...")


def test_delivery_skips_disabled_subscription():
    """Test that delivery is skipped for disabled subscriptions."""
    sub = WebhookSubscription("https://example.com/hook", ["task.completed"])
    sub.disable()
    delivery = WebhookDelivery()
    result = delivery.deliver(sub, {"event": "task.completed"})
    assert result["status"] == "skipped"
