"""Tests for idempotent checkpoint storage with deterministic keys."""

import unittest
import time
from src.orchestrator.checkpoint import CheckpointStore, CheckpointRecord, DigestMismatchError


class TestCheckpointRecord(unittest.TestCase):
    """Test CheckpointRecord dataclass."""
    
    def test_deterministic_key(self):
        """Key should be deterministic: task_id:step_id:attempt_id."""
        record = CheckpointRecord(
            task_id="task-001",
            step_id="step-1",
            attempt_id="attempt-1",
            content={"progress": 50},
            digest="abc123",
        )
        self.assertEqual(record.key, "task-001:step-1:attempt-1")
    
    def test_compute_digest(self):
        """Digest should be SHA-256 of content."""
        content1 = {"a": 1, "b": 2}
        content2 = {"b": 2, "a": 1}  # Same but different order
        
        digest1 = CheckpointRecord.compute_digest(content1)
        digest2 = CheckpointRecord.compute_digest(content2)
        
        # Should be identical (sorted keys)
        self.assertEqual(digest1, digest2)
        self.assertEqual(len(digest1), 64)  # SHA-256 hex length
    
    def test_to_dict(self):
        """Should serialize to dictionary."""
        record = CheckpointRecord(
            task_id="task-001",
            step_id="step-1",
            attempt_id="attempt-1",
            content={"data": "value"},
            digest="abc123",
        )
        d = record.to_dict()
        self.assertEqual(d["task_id"], "task-001")
        self.assertEqual(d["step_id"], "step-1")
        self.assertEqual(d["attempt_id"], "attempt-1")
        self.assertEqual(d["content"], {"data": "value"})
        self.assertEqual(d["digest"], "abc123")
    
    def test_from_dict(self):
        """Should deserialize from dictionary."""
        data = {
            "task_id": "task-001",
            "step_id": "step-1",
            "attempt_id": "attempt-1",
            "content": {"data": "value"},
            "digest": "abc123",
            "created_at": 1000.0,
            "updated_at": 1001.0,
        }
        record = CheckpointRecord.from_dict(data)
        self.assertEqual(record.task_id, "task-001")
        self.assertEqual(record.digest, "abc123")


class TestCheckpointStore(unittest.TestCase):
    """Test CheckpointStore with idempotent upsert semantics."""
    
    def setUp(self):
        self.store = CheckpointStore()
    
    def test_write_first_time(self):
        """First write should succeed."""
        record = self.store.write(
            task_id="task-001",
            step_id="step-1",
            attempt_id="attempt-1",
            content={"progress": 50},
        )
        self.assertIsInstance(record, CheckpointRecord)
        self.assertEqual(record.task_id, "task-001")
    
    def test_write_idempotent_same_digest(self):
        """Writing same content twice should return existing record (idempotent)."""
        content = {"progress": 50}
        
        record1 = self.store.write("task-001", "step-1", "attempt-1", content)
        record2 = self.store.write("task-001", "step-1", "attempt-1", content)
        
        # Should be the same record
        self.assertEqual(record1.key, record2.key)
        self.assertEqual(record1.digest, record2.digest)
        # Should not create duplicate
        self.assertEqual(len(self.store.list_by_task("task-001")), 1)
    
    def test_write_different_digest_raises_error(self):
        """Writing different content with same key should raise DigestMismatchError."""
        self.store.write("task-001", "step-1", "attempt-1", {"progress": 50})
        
        with self.assertRaises(DigestMismatchError) as cm:
            self.store.write("task-001", "step-1", "attempt-1", {"progress": 100})
        
        self.assertIn("different digest", str(cm.exception))
    
    def test_read_existing(self):
        """Should read existing checkpoint."""
        self.store.write("task-001", "step-1", "attempt-1", {"data": "value"})
        
        record = self.store.read("task-001", "step-1", "attempt-1")
        self.assertIsNotNone(record)
        self.assertEqual(record.content["data"], "value")
    
    def test_read_nonexistent(self):
        """Should return None for non-existent checkpoint."""
        record = self.store.read("task-001", "step-1", "attempt-1")
        self.assertIsNone(record)
    
    def test_read_latest(self):
        """Should return checkpoint with highest attempt_id."""
        self.store.write("task-001", "step-1", "attempt-1", {"v": 1})
        self.store.write("task-001", "step-1", "attempt-3", {"v": 3})
        self.store.write("task-001", "step-1", "attempt-2", {"v": 2})
        
        latest = self.store.read_latest("task-001", "step-1")
        self.assertEqual(latest.attempt_id, "attempt-3")
    
    def test_read_latest_nonexistent(self):
        """Should return None if no checkpoints exist for task/step."""
        latest = self.store.read_latest("task-001", "step-1")
        self.assertIsNone(latest)
    
    def test_delete_existing(self):
        """Should delete existing checkpoint."""
        self.store.write("task-001", "step-1", "attempt-1", {"data": "value"})
        
        result = self.store.delete("task-001", "step-1", "attempt-1")
        self.assertTrue(result)
        self.assertIsNone(self.store.read("task-001", "step-1", "attempt-1"))
    
    def test_delete_nonexistent(self):
        """Should return False when deleting non-existent checkpoint."""
        result = self.store.delete("task-001", "step-1", "attempt-1")
        self.assertFalse(result)
    
    def test_list_by_task(self):
        """Should list all checkpoints for a task."""
        self.store.write("task-001", "step-1", "attempt-1", {"v": 1})
        self.store.write("task-001", "step-2", "attempt-1", {"v": 2})
        self.store.write("task-002", "step-1", "attempt-1", {"v": 3})
        
        task1_checkpoints = self.store.list_by_task("task-001")
        self.assertEqual(len(task1_checkpoints), 2)
    
    def test_clear(self):
        """Should clear all checkpoints."""
        self.store.write("task-001", "step-1", "attempt-1", {"v": 1})
        self.store.write("task-002", "step-1", "attempt-1", {"v": 2})
        
        self.store.clear()
        self.assertEqual(len(self.store.list_by_task("task-001")), 0)
        self.assertEqual(len(self.store.list_by_task("task-002")), 0)


class TestCheckpointRetryBehavior(unittest.TestCase):
    """Test checkpoint behavior during task retries and timeouts."""
    
    def setUp(self):
        self.store = CheckpointStore()
    
    def test_retry_creates_new_attempt_key(self):
        """Retry should use new attempt_id, creating separate checkpoint."""
        # Initial attempt
        self.store.write("task-001", "step-1", "attempt-1", {"status": "in_progress"})
        
        # Retry with new attempt_id
        self.store.write("task-001", "step-1", "attempt-2", {"status": "retried"})
        
        # Should have two separate checkpoints
        self.assertEqual(len(self.store.list_by_task("task-001")), 2)
        
        # Latest should be attempt-2
        latest = self.store.read_latest("task-001", "step-1")
        self.assertEqual(latest.attempt_id, "attempt-2")
    
    def test_timeout_checkpoint(self):
        """Timeout should create checkpoint for resumption."""
        timeout_content = {
            "status": "timeout",
            "progress": 75,
            "timeout_at": time.time(),
        }
        
        record = self.store.write("task-001", "step-1", "attempt-1", timeout_content)
        self.assertEqual(record.content["status"], "timeout")
        self.assertEqual(record.content["progress"], 75)
    
    def test_resume_from_checkpoint(self):
        """Should be able to resume from checkpoint."""
        checkpoint_data = {
            "status": "in_progress",
            "progress": 50,
            "intermediate_results": {"partial": "data"},
        }
        
        self.store.write("task-001", "step-1", "attempt-1", checkpoint_data)
        
        # Resume
        record = self.store.read("task-001", "step-1", "attempt-1")
        self.assertEqual(record.content["progress"], 50)
        self.assertEqual(record.content["intermediate_results"]["partial"], "data")
    
    def test_idempotent_retry_same_attempt(self):
        """Retrying with same attempt_id should be idempotent if content matches."""
        content = {"status": "in_progress", "progress": 50}
        
        # Write checkpoint
        r1 = self.store.write("task-001", "step-1", "attempt-1", content)
        
        # Retry with same content (e.g., network retry)
        r2 = self.store.write("task-001", "step-1", "attempt-1", content)
        
        # Should return same record (idempotent)
        self.assertEqual(r1.key, r2.key)
        self.assertEqual(self.store.list_by_task("task-001"), 1)  # Only one record


if __name__ == "__main__":
    unittest.main()
