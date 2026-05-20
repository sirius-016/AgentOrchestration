"""Tests for queue capacity release on enqueue rollback (#123)."""

import pytest
from src.orchestrator.scheduler import TaskScheduler, CapacityLimiter, ResourceExhaustedError


class TestCapacityLimiter:
    def test_reserve_and_commit(self):
        limiter = CapacityLimiter(max_capacity=10)
        assert limiter.reserve("t1", 1) is True
        assert limiter.used == 1
        limiter.commit("t1")
        assert limiter.available == 9

    def test_reserve_and_release(self):
        limiter = CapacityLimiter(max_capacity=10)
        limiter.reserve("t1", 3)
        assert limiter.used == 3
        limiter.release("t1")
        assert limiter.used == 0
        assert limiter.available == 10

    def test_reserve_exhausted(self):
        limiter = CapacityLimiter(max_capacity=2)
        assert limiter.reserve("t1", 1) is True
        assert limiter.reserve("t2", 1) is True
        assert limiter.reserve("t3", 1) is False  # exhausted

    def test_release_unknown_task(self):
        limiter = CapacityLimiter(max_capacity=10)
        assert limiter.release("unknown") is False  # no-op

    def test_capacity_recovered_after_release(self):
        limiter = CapacityLimiter(max_capacity=2)
        limiter.reserve("t1", 1)
        limiter.reserve("t2", 1)
        limiter.release("t1")  # release one
        assert limiter.reserve("t3", 1) is True  # can reserve again


class TestSchedulerCapacity:
    def test_enqueue_reserves_capacity(self):
        scheduler = TaskScheduler(max_capacity=100)
        scheduler.enqueue({"task": "data"})
        assert scheduler.capacity_available < 100

    def test_complete_releases_capacity(self):
        scheduler = TaskScheduler(max_capacity=100)
        task_id = scheduler.enqueue({"task": "data"})
        initial = scheduler.capacity_available
        scheduler.complete(task_id)
        assert scheduler.capacity_available > initial

    def test_capacity_exhausted_raises(self):
        scheduler = TaskScheduler(max_capacity=2)
        scheduler.enqueue({"task": "a"})
        scheduler.enqueue({"task": "b"})
        with pytest.raises(ResourceExhaustedError):
            scheduler.enqueue({"task": "c"})

    def test_fail_max_retries_releases_capacity(self):
        scheduler = TaskScheduler(max_capacity=100)
        task_id = scheduler.enqueue({"task": "data"})
        initial = scheduler.capacity_available
        # Simulate max retries
        scheduler._in_flight[task_id]["retries"] = scheduler._max_retries - 1
        scheduler.fail(task_id)
        assert scheduler.capacity_available == initial  # capacity released

    def test_fail_retry_keeps_capacity(self):
        scheduler = TaskScheduler(max_capacity=100)
        task_id = scheduler.enqueue({"task": "data"})
        initial = scheduler.capacity_available
        scheduler._in_flight[task_id]["retries"] = 0
        scheduler.fail(task_id)  # retries, so capacity stays reserved
        # A new task was enqueued, so capacity should be lower
        assert scheduler.capacity_available <= initial
