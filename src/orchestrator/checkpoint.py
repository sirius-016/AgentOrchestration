"""Checkpoint Store — Idempotent checkpoint persistence with deterministic keys."""

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class CheckpointRecord:
    """A checkpoint record with deterministic key and content digest."""
    
    task_id: str
    step_id: str
    attempt_id: str
    content: Dict[str, Any]
    digest: str
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    
    @property
    def key(self) -> str:
        """Generate deterministic key from task_id + step_id + attempt_id."""
        return f"{self.task_id}:{self.step_id}:{self.attempt_id}"
    
    @staticmethod
    def compute_digest(content: Dict[str, Any]) -> str:
        """Compute SHA-256 digest of content."""
        content_str = json.dumps(content, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(content_str.encode('utf-8')).hexdigest()
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            'task_id': self.task_id,
            'step_id': self.step_id,
            'attempt_id': self.attempt_id,
            'content': self.content,
            'digest': self.digest,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CheckpointRecord':
        """Deserialize from dictionary."""
        return cls(
            task_id=data['task_id'],
            step_id=data['step_id'],
            attempt_id=data['attempt_id'],
            content=data['content'],
            digest=data['digest'],
            created_at=data.get('created_at', time.time()),
            updated_at=data.get('updated_at', time.time()),
        )


class CheckpointStore:
    """Idempotent checkpoint storage with upsert semantics.
    
    Uses deterministic keys (task_id + step_id + attempt_id) to ensure
    that retried checkpoint writes produce exactly one logical record.
    
    Upsert semantics:
    - If key exists with same digest: return existing record (idempotent)
    - If key exists with different digest: raise DigestMismatchError
    - If key doesn't exist: create new record
    """
    
    def __init__(self):
        self._store: Dict[str, CheckpointRecord] = {}
    
    def write(
        self,
        task_id: str,
        step_id: str,
        attempt_id: str,
        content: Dict[str, Any],
    ) -> CheckpointRecord:
        """Write a checkpoint with idempotent upsert semantics.
        
        Args:
            task_id: Unique task identifier
            step_id: Step identifier within the task
            attempt_id: Attempt identifier for retry handling
            content: Checkpoint content to persist
            
        Returns:
            CheckpointRecord: The written or existing record
            
        Raises:
            DigestMismatchError: If key exists with different content
        """
        digest = CheckpointRecord.compute_digest(content)
        key = f"{task_id}:{step_id}:{attempt_id}"
        
        if key in self._store:
            existing = self._store[key]
            
            # Idempotent: same digest, return existing
            if existing.digest == digest:
                logger.debug(f"Checkpoint {key} already exists with same digest, returning existing")
                return existing
            
            # Different digest: fail loudly
            raise DigestMismatchError(
                f"Checkpoint {key} exists with different digest. "
                f"Existing: {existing.digest}, New: {digest}"
            )
        
        # New checkpoint
        record = CheckpointRecord(
            task_id=task_id,
            step_id=step_id,
            attempt_id=attempt_id,
            content=content,
            digest=digest,
        )
        self._store[key] = record
        logger.info(f"Created checkpoint {key} with digest {digest}")
        return record
    
    def read(
        self,
        task_id: str,
        step_id: str,
        attempt_id: str,
    ) -> Optional[CheckpointRecord]:
        """Read a checkpoint by its deterministic key.
        
        Args:
            task_id: Unique task identifier
            step_id: Step identifier within the task
            attempt_id: Attempt identifier for retry handling
            
        Returns:
            CheckpointRecord if found, None otherwise
        """
        key = f"{task_id}:{step_id}:{attempt_id}"
        return self._store.get(key)
    
    def read_latest(
        self,
        task_id: str,
        step_id: str,
    ) -> Optional[CheckpointRecord]:
        """Read the latest checkpoint for a task/step across all attempts.
        
        Args:
            task_id: Unique task identifier
            step_id: Step identifier within the task
            
        Returns:
            CheckpointRecord with highest attempt_id if found, None otherwise
        """
        prefix = f"{task_id}:{step_id}:"
        matching = [
            record for key, record in self._store.items()
            if key.startswith(prefix)
        ]
        
        if not matching:
            return None
        
        # Return the one with highest attempt_id (lexicographically)
        return max(matching, key=lambda r: r.attempt_id)
    
    def delete(
        self,
        task_id: str,
        step_id: str,
        attempt_id: str,
    ) -> bool:
        """Delete a checkpoint by its deterministic key.
        
        Args:
            task_id: Unique task identifier
            step_id: Step identifier within the task
            attempt_id: Attempt identifier for retry handling
            
        Returns:
            True if deleted, False if not found
        """
        key = f"{task_id}:{step_id}:{attempt_id}"
        if key in self._store:
            del self._store[key]
            logger.info(f"Deleted checkpoint {key}")
            return True
        return False
    
    def list_by_task(self, task_id: str) -> list[CheckpointRecord]:
        """List all checkpoints for a given task.
        
        Args:
            task_id: Unique task identifier
            
        Returns:
            List of CheckpointRecords for the task
        """
        prefix = f"{task_id}:"
        return [record for key, record in self._store.items() if key.startswith(prefix)]
    
    def clear(self) -> None:
        """Clear all checkpoints (useful for testing)."""
        self._store.clear()
        logger.info("Cleared all checkpoints")


class DigestMismatchError(Exception):
    """Raised when attempting to overwrite a checkpoint with different content."""
    pass
