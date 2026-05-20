"""Tests for idempotent dead-letter queue writes (#141)."""
import pytest, time
from src.queue.dead_letter import DeadLetterQueue

class TestDeadLetterIdempotency:
    def test_first_write_creates_message(self):
        dlq = DeadLetterQueue()
        assert dlq.add("msg-1", "default", {"data": 1}, "error") == "msg-1"
        assert dlq.count() == 1

    def test_duplicate_write_is_idempotent(self):
        dlq = DeadLetterQueue()
        dlq.add("msg-1", "default", {"data": 1}, "error")
        dlq.add("msg-1", "default", {"data": 1}, "error")
        assert dlq.count() == 1

    def test_duplicate_write_returns_same_id(self):
        dlq = DeadLetterQueue()
        assert dlq.add("msg-1", "default", {"data": 1}, "error") == dlq.add("msg-1", "default", {"data": 1}, "error")

    def test_duplicate_write_does_not_overwrite(self):
        dlq = DeadLetterQueue()
        dlq.add("msg-1", "default", {"original": True}, "original error")
        dlq.add("msg-1", "default", {"modified": True}, "different error")
        raw = dlq.get_raw_message("msg-1", actor="test", reason="verify")
        assert raw["payload"] == {"original": True}

    def test_different_message_ids_are_separate(self):
        dlq = DeadLetterQueue()
        dlq.add("msg-1", "default", {"data": 1}, "error1")
        dlq.add("msg-2", "default", {"data": 2}, "error2")
        assert dlq.count() == 2

    def test_acknowledge_id_tracked(self):
        dlq = DeadLetterQueue()
        dlq.add("msg-1", "default", {"data": 1}, "error", acknowledge_id="ack-1")
        dlq.add("msg-1", "default", {"data": 1}, "error", acknowledge_id="ack-2")
        assert dlq.count() == 1
        assert dlq._write_log["msg-1"] == 2

    def test_many_retries_still_idempotent(self):
        dlq = DeadLetterQueue()
        for i in range(100): dlq.add("msg-1", "default", {"data": 1}, "error", acknowledge_id=f"ack-{i}")
        assert dlq.count() == 1

    def test_remove_then_readd_creates_new(self):
        dlq = DeadLetterQueue()
        dlq.add("msg-1", "default", {"data": 1}, "error")
        dlq.remove("msg-1")
        dlq.add("msg-1", "default", {"data": 2}, "new error")
        raw = dlq.get_raw_message("msg-1", actor="test", reason="verify")
        assert raw["payload"] == {"data": 2}
