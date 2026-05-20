"""Dead-letter queue management with payload redaction and idempotent writes."""

import hashlib, json, logging, re, time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SENSITIVE_KEY_PATTERNS = [
    re.compile(r"password", re.IGNORECASE), re.compile(r"secret", re.IGNORECASE),
    re.compile(r"token", re.IGNORECASE), re.compile(r"api[_-]?key", re.IGNORECASE),
    re.compile(r"auth", re.IGNORECASE), re.compile(r"credential", re.IGNORECASE),
    re.compile(r"private[_-]?key", re.IGNORECASE),
]
MAX_EXCERPT_LENGTH = 128

class DeadLetterMessage:
    def __init__(self, message_id, queue, payload, error, enqueued_at, dead_at, metadata=None):
        self.message_id = message_id; self.queue = queue; self.payload = payload
        self.error = error; self.enqueued_at = enqueued_at; self.dead_at = dead_at
        self.metadata = metadata or {}

    def to_dict(self, include_payload=False):
        result = {"message_id": self.message_id, "queue": self.queue, "error": self.error,
                  "enqueued_at": self.enqueued_at, "dead_at": self.dead_at,
                  "metadata": self._redact_dict(self.metadata), "payload_digest": self._payload_digest()}
        if include_payload: result["payload"] = self.payload
        else: result["payload_summary"] = self._summarize_payload()
        return result

    def _payload_digest(self):
        return hashlib.sha256(json.dumps(self.payload, sort_keys=True, default=str).encode()).hexdigest()[:16]

    def _summarize_payload(self):
        raw = json.dumps(self.payload, sort_keys=True, default=str)
        return raw[:MAX_EXCERPT_LENGTH] + "... [REDACTED]" if len(raw) > MAX_EXCERPT_LENGTH else raw

    @staticmethod
    def _redact_dict(data):
        r = {}
        for k, v in data.items():
            if any(p.search(k) for p in SENSITIVE_KEY_PATTERNS): r[k] = "***REDACTED***"
            elif isinstance(v, dict): r[k] = DeadLetterMessage._redact_dict(v)
            else: r[k] = v
        return r

class DeadLetterQueue:
    """Dead-letter queue with redacted default view, audited raw-data access,
    and idempotent writes."""

    def __init__(self):
        self._messages: Dict[str, DeadLetterMessage] = {}
        self._audit_log: List[Dict[str, Any]] = []
        self._write_log: Dict[str, int] = {}

    def add(self, message_id, queue, payload, error, enqueued_at=None, metadata=None, acknowledge_id=None):
        if message_id in self._messages:
            self._write_log[message_id] = self._write_log.get(message_id, 1) + 1
            logger.info(f"Dead-letter write idempotent skip: {message_id} (write #{self._write_log[message_id]}, ack_id={acknowledge_id})")
            return message_id
        msg = DeadLetterMessage(message_id, queue, payload, error, enqueued_at or time.time(), time.time(), metadata)
        self._messages[message_id] = msg
        self._write_log[message_id] = 1
        logger.info(f"Dead-letter message added: {message_id} from queue {queue}")
        return message_id

    def list_messages(self, queue=None):
        msgs = self._messages.values()
        if queue: msgs = [m for m in msgs if m.queue == queue]
        return [m.to_dict(include_payload=False) for m in msgs]

    def get_raw_message(self, message_id, actor, reason):
        msg = self._messages.get(message_id)
        if not msg: return None
        self._audit_log.append({"timestamp": time.time(), "action": "raw_data_access", "message_id": message_id, "actor": actor, "reason": reason})
        logger.info(f"Dead-letter raw data access: message={message_id} actor={actor} reason={reason}")
        return msg.to_dict(include_payload=True)

    def get_audit_log(self, message_id=None):
        if message_id: return [e for e in self._audit_log if e.get("message_id") == message_id]
        return list(self._audit_log)

    def remove(self, message_id):
        if message_id in self._messages:
            del self._messages[message_id]; self._write_log.pop(message_id, None); return True
        return False

    def count(self, queue=None):
        if queue: return sum(1 for m in self._messages.values() if m.queue == queue)
        return len(self._messages)
