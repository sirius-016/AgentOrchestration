"""Dead-letter queue management with payload redaction and idempotent writes."""

import hashlib
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SENSITIVE_KEY_PATTERNS = [
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"token", re.IGNORECASE),
    re.compile(r"api[_-]?key", re.IGNORECASE),
    re.compile(r"auth", re.IGNORECASE),
    re.compile(r"credential", re.IGNORECASE),
    re.compile(r"private[_-]?key", re.IGNORECASE),
]

MAX_EXCERPT_LENGTH = 128


class DeadLetterMessage:
    """Represents a message in the dead-letter queue."""

    def __init__(self, message_id: str, queue: str, payload: Any, error: str,
                 enqueued_at: float, dead_at: float, metadata: Optional[Dict] = None):
        self.message_id = message_id
        self.queue = queue
        self.payload = payload
        self.error = error
        self.enqueued_at = enqueued_at
        self.dead_at = dead_at
        self.metadata = metadata or {}

    def to_dict(self, include_payload: bool = False) -> Dict[str, Any]:
        result = {
            "message_id": self.message_id,
            "queue": self.queue,
            "error": self.error,
            "enqueued_at": self.enqueued_at,
            "dead_at": self.dead_at,
            "metadata": self._redact_dict(self.metadata),
            "payload_digest": self._payload_digest(),
        }
        if include_payload:
            result["payload"] = self.payload
        else:
            result["payload_summary"] = self._summarize_payload()
        return result

    def _payload_digest(self) -> str:
        raw = json.dumps(self.payload, sort_keys=True, default=str).encode()
        return hashlib.sha256(raw).hexdigest()[:16]

    def _summarize_payload(self) -> str:
        raw = json.dumps(self.payload, sort_keys=True, default=str)
        if len(raw) > MAX_EXCERPT_LENGTH:
            return raw[:MAX_EXCERPT_LENGTH] + "... [REDACTED]"
        return raw

    @staticmethod
    def _redact_dict(data: Dict) -> Dict:
        redacted = {}
        for key, value in data.items():
            if any(pattern.search(key) for pattern in SENSITIVE_KEY_PATTERNS):
                redacted[key] = "***REDACTED***"
            elif isinstance(value, dict):
                redacted[key] = DeadLetterMessage._redact_dict(value)
            else:
                redacted[key] = value
        return redacted


class DeadLetterQueue:
    """Dead-letter queue with redacted default view, audited raw-data access,
    and idempotent writes.

    Dead-letter writes are idempotent: re-adding a message with the same
    message_id is a no-op that returns the existing message_id without
    duplicating data or triggering duplicate audit entries. This prevents
    acknowledgement retries from creating duplicate dead-letter records.
    """

    def __init__(self):
        self._messages: Dict[str, DeadLetterMessage] = {}
        self._audit_log: List[Dict[str, Any]] = []
        self._write_log: Dict[str, int] = {}  # message_id -> write count for dedup

    def add(self, message_id: str, queue: str, payload: Any, error: str,
            enqueued_at: Optional[float] = None, metadata: Optional[Dict] = None,
            acknowledge_id: Optional[str] = None) -> str:
        """Add a message to the dead-letter queue (idempotent).

        If a message with the same message_id already exists, this is a no-op.
        The acknowledge_id tracks which acknowledgement attempt triggered this write.
        """
        if message_id in self._messages:
            write_count = self._write_log.get(message_id, 1) + 1
            self._write_log[message_id] = write_count
            logger.info(
                f"Dead-letter write idempotent skip: {message_id} "
                f"(write #{write_count}, ack_id={acknowledge_id})"
            )
            return message_id

        msg = DeadLetterMessage(
            message_id=message_id,
            queue=queue,
            payload=payload,
            error=error,
            enqueued_at=enqueued_at or time.time(),
            dead_at=time.time(),
            metadata=metadata,
        )
        self._messages[message_id] = msg
        self._write_log[message_id] = 1
        logger.info(f"Dead-letter message added: {message_id} from queue {queue}")
        return message_id

    def list_messages(self, queue: Optional[str] = None) -> List[Dict[str, Any]]:
        messages = self._messages.values()
        if queue:
            messages = [m for m in messages if m.queue == queue]
        return [m.to_dict(include_payload=False) for m in messages]

    def get_raw_message(self, message_id: str, actor: str, reason: str) -> Optional[Dict[str, Any]]:
        msg = self._messages.get(message_id)
        if not msg:
            return None
        audit_entry = {
            "timestamp": time.time(),
            "action": "raw_data_access",
            "message_id": message_id,
            "actor": actor,
            "reason": reason,
        }
        self._audit_log.append(audit_entry)
        logger.info(f"Dead-letter raw data access: message={message_id} actor={actor} reason={reason}")
        return msg.to_dict(include_payload=True)

    def get_audit_log(self, message_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if message_id:
            return [e for e in self._audit_log if e.get("message_id") == message_id]
        return list(self._audit_log)

    def remove(self, message_id: str) -> bool:
        if message_id in self._messages:
            del self._messages[message_id]
            self._write_log.pop(message_id, None)
            return True
        return False

    def count(self, queue: Optional[str] = None) -> int:
        if queue:
            return sum(1 for m in self._messages.values() if m.queue == queue)
        return len(self._messages)
