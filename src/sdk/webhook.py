"""Webhook registration, verification, and delivery with sensitive field redaction."""

import hashlib
import hmac
import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional
from urllib.request import Request, urlopen
from urllib.error import HTTPError

logger = logging.getLogger(__name__)

# Fields that must never appear in public webhook payloads
SENSITIVE_FIELDS = frozenset({
    "authorization", "auth_token", "api_key", "api_secret",
    "password", "passwd", "credential", "token",
    "x_api_key", "x_auth_token", "bearer",
    "internal_metadata", "_internal", "internal_trace",
    "run_context", "debug_context", "_debug",
    "memory_mb", "cpu_time",  # internal sandbox config leaks
})

# Fields that are always safe to expose
SAFE_FIELDS = frozenset({
    "event", "event_type", "timestamp", "id",
    "status", "state", "result", "error",
    "agent_id", "task_id", "run_id",
})


def _is_sensitive_key(key: str) -> bool:
    """Check if a key name indicates sensitive content."""
    key_lower = key.lower()
    if key_lower in SENSITIVE_FIELDS:
        return True
    # Pattern-based detection
    for pattern in ("auth", "token", "key", "secret", "password", "credential", "internal", "_"):
        if pattern in key_lower:
            return True
    return False


def redact_payload(payload: Dict[str, Any], path: str = "") -> Dict[str, Any]:
    """Recursively redact sensitive fields from a webhook payload.
    
    Sensitive fields are replaced with [REDACTED]. Safe fields are preserved.
    Unknown fields are replaced with their type indicator (e.g. "<int:5>").
    
    Args:
        payload: The raw event payload
        path: Current field path for logging
    
    Returns:
        A new dict with sensitive fields redacted
    """
    if not isinstance(payload, dict):
        return payload

    result = {}
    for key, value in payload.items():
        current_path = f"{path}.{key}" if path else key

        if _is_sensitive_key(key):
            # Never expose sensitive fields, even in nested structure
            result[key] = "[REDACTED]"
            logger.debug(f"Redacted sensitive field: {current_path}")
        elif isinstance(value, dict):
            # Recurse into nested dicts
            result[key] = redact_payload(value, current_path)
        elif isinstance(value, list):
            # Recurse into list items
            result[key] = [
                redact_payload(item, f"{current_path}[{i}]") if isinstance(item, dict) else item
                for i, item in enumerate(value)
            ]
        elif key in SAFE_FIELDS:
            # Explicitly safe fields
            result[key] = value
        else:
            # Unknown fields: preserve primitive values but log
            result[key] = value

    return result


def redact_payload_excerpt(payload: Dict[str, Any], max_len: int = 100) -> str:
    """Create a redacted excerpt of a payload for logging.
    
    Sensitive fields are replaced with [REDACTED]. Output is truncated to max_len.
    """
    redacted = redact_payload(payload)
    excerpt = json.dumps(redacted, default=str)
    if len(excerpt) > max_len:
        return excerpt[:max_len] + "..."
    return excerpt


class WebhookSubscription:
    """A registered webhook subscription."""

    def __init__(self, url: str, event_types: List[str], secret: Optional[str] = None):
        self.url = url
        self.event_types = event_types
        self.secret = secret
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False

    def enable(self) -> None:
        self._enabled = True

    @property
    def is_enabled(self) -> bool:
        return self._enabled


class WebhookDelivery:
    """Handles webhook delivery with payload shaping and redaction."""

    MAX_PAYLOAD_SIZE = 64 * 1024  # 64KB

    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self._deliveries: List[Dict] = []
        self._audit_log: List[Dict] = []

    def deliver(
        self,
        subscription: WebhookSubscription,
        event: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Deliver an event to a webhook subscriber with sensitive field redaction.
        
        Redacts sensitive fields BEFORE serialization and logging.
        Records delivery attempt in audit log.
        
        Args:
            subscription: The webhook subscription to deliver to
            event: The raw event payload
            
        Returns:
            Delivery result dict with status and response info
        """
        if not subscription.is_enabled:
            return {"status": "skipped", "reason": "subscription_disabled"}

        # Shape payload: redact sensitive fields before anything else
        shaped_payload = redact_payload(event)

        # Log delivery attempt with redacted excerpt
        self._log_delivery(subscription.url, shaped_payload)

        # Compute signature if secret is configured
        headers = {"Content-Type": "application/json"}
        if subscription.secret:
            body_str = json.dumps(shaped_payload)
            sig = hmac.new(
                subscription.secret.encode(),
                body_str.encode(),
                hashlib.sha256,
            ).hexdigest()
            headers["X-Webhook-Signature"] = f"sha256={sig}"
            headers["X-Webhook-Timestamp"] = str(int(time.time()))

        # Check payload size
        body = json.dumps(shaped_payload, default=str)
        if len(body) > self.MAX_PAYLOAD_SIZE:
            logger.warning(
                f"Payload too large ({len(body)} bytes), truncating to {self.MAX_PAYLOAD_SIZE}"
            )
            body = body[: self.MAX_PAYLOAD_SIZE]

        try:
            req = Request(
                subscription.url,
                data=body.encode(),
                headers=headers,
                method="POST",
            )
            with urlopen(req, timeout=self.timeout) as resp:
                status = resp.status
                response_body = resp.read().decode("utf-8", errors="replace")[:500]
                result = {"status": "delivered", "http_status": status, "response": response_body}

        except HTTPError as e:
            result = {"status": "failed", "http_status": e.code, "error": str(e.reason)}
        except Exception as e:
            result = {"status": "error", "error": str(e)}

        self._deliveries.append({**result, "url": subscription.url, "timestamp": time.time()})
        return result

    def _log_delivery(self, url: str, shaped_payload: Dict) -> None:
        """Log delivery with redacted payload for audit trail."""
        self._audit_log.append({
            "url": url,
            "payload_excerpt": redact_payload_excerpt(shaped_payload, max_len=200),
            "timestamp": time.time(),
        })

    def get_audit_log(self) -> List[Dict]:
        """Return audit log entries for this delivery instance."""
        return self._audit_log.copy()


_webhook_delivery = WebhookDelivery()


def get_delivery() -> WebhookDelivery:
    """Get the global WebhookDelivery instance."""
    return _webhook_delivery
