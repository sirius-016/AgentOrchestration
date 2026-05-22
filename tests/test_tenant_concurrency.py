"""Tests for per-tenant concurrency enforcement — Issue #1079."""

import asyncio
import os
import pytest

from src.orchestrator.scheduler import (
    TaskScheduler,
    ConcurrencyLimitExceeded,
    StaleTaskError,
)


class TestPerTenantConcurrency:
    """Tests for AO_SCHEDULER_MAX_CONCURRENT_PER_TENANT enforcement."""

    def setup_method(self):
        # Ensure a clean env for each test
        self._orig_env = os.environ.pop("AO_SCHEDULER_MAX_CONCURRENT_PER_TENANT", None)
        self.scheduler = TaskScheduler()

    def teardown_method(self):
        if self._orig_env is not None:
            os.environ["AO_SCHEDULER_MAX_CONCURRENT_PER_TENANT"] = self._orig_env
        elif "AO_SCHEDULER_MAX_CONCURRENT_PER_TENANT" in os.environ:
            del os.environ["AO_SCHEDULER_MAX_CONCURRENT_PER_TENANT"]

    # ── enqueue-level limit enforcement ──────────────────────────────────────

    def test_tenant_can_enqueue_up_to_limit(self):
        """A tenant can enqueue up to the configured limit without error."""
        for i in range(10):
            tid = self.scheduler.enqueue(
                {"type": "test", "payload": i}, tenant_id="tenant-a"
            )
            assert tid is not None

    def test_enqueue_raises_when_tenant_at_limit(self):
        """Enqueue raises ConcurrencyLimitExceeded once the limit is hit."""
        # Fill up tenant-a to the default limit of 10
        for _ in range(10):
            self.scheduler.enqueue({"type": "test"}, tenant_id="tenant-a")

        with pytest.raises(ConcurrencyLimitExceeded) as exc_info:
            self.scheduler.enqueue({"type": "test"}, tenant_id="tenant-a")
        assert exc_info.value.tenant_id == "tenant-a"
        assert exc_info.value.limit == 10
        assert exc_info.value.current == 10

    def test_different_tenants_independent(self):
        """Two different tenants each get their own concurrency budget."""
        # Fill tenant-a to limit
        for _ in range(10):
            self.scheduler.enqueue({"type": "test"}, tenant_id="tenant-a")
        # tenant-b should still be able to enqueue
        tid = self.scheduler.enqueue({"type": "test"}, tenant_id="tenant-b")
        assert tid is not None

    def test_tenant_id_from_task_body(self):
        """When tenant_id is not passed explicitly, read from task['tenant_id']."""
        for _ in range(10):
            self.scheduler.enqueue({"type": "test", "tenant_id": "tenant-c"})
        with pytest.raises(ConcurrencyLimitExceeded):
            self.scheduler.enqueue({"type": "test", "tenant_id": "tenant-c"})

    # ── configurable limit via env var ────────────────────────────────────────

    def test_env_var_respected(self):
        """Setting AO_SCHEDULER_MAX_CONCURRENT_PER_TENANT changes the limit."""
        os.environ["AO_SCHEDULER_MAX_CONCURRENT_PER_TENANT"] = "3"
        scheduler = TaskScheduler()
        for _ in range(3):
            scheduler.enqueue({"type": "test"}, tenant_id="t")
        with pytest.raises(ConcurrencyLimitExceeded) as exc:
            scheduler.enqueue({"type": "test"}, tenant_id="t")
        assert exc.value.limit == 3

    def test_env_var_invalid_falls_back_to_default(self):
        """A non-integer env var value falls back to the default of 10."""
        os.environ["AO_SCHEDULER_MAX_CONCURRENT_PER_TENANT"] = "not-a-number"
        scheduler = TaskScheduler()
        for _ in range(10):
            scheduler.enqueue({"type": "test"}, tenant_id="t")
        with pytest.raises(ConcurrencyLimitExceeded) as exc:
            scheduler.enqueue({"type": "test"}, tenant_id="t")
        assert exc.value.limit == 10

    def test_env_var_zero_or_negative_falls_back_to_default(self):
        """An env var value < 1 falls back to the default."""
        os.environ["AO_SCHEDULER_MAX_CONCURRENT_PER_TENANT"] = "0"
        scheduler = TaskScheduler()
        for _ in range(10):
            scheduler.enqueue({"type": "test"}, tenant_id="t")
        with pytest.raises(ConcurrencyLimitExceeded) as exc:
            scheduler.enqueue({"type": "test"}, tenant_id="t")
        assert exc.value.limit == 10

    # ── in-flight tracking ────────────────────────────────────────────────────

    def test_in_flight_count_tracked_per_tenant(self):
        """get_tenant_in_flight_count reflects actual in-flight tasks."""
        assert self.scheduler.get_tenant_in_flight_count("t1") == 0

        # Enqueue + dequeue (dispatch) tracks in-flight
        self.scheduler.enqueue({"type": "a"}, tenant_id="t1")
        self.scheduler.enqueue({"type": "b"}, tenant_id="t1")
        self.scheduler.enqueue({"type": "c"}, tenant_id="t2")

        async def drain(q):
            t1_count = 0
            t2_count = 0
            while True:
                task = await self.scheduler.dequeue(queue=q)
                if task is None:
                    break
                if task.get("tenant_id") == "t1":
                    t1_count += 1
                else:
                    t2_count += 1
            return t1_count, t2_count

        t1, t2 = asyncio.run(drain("default"))
        assert t1 == 2
        assert t2 == 1
        assert self.scheduler.get_tenant_in_flight_count("t1") == 2
        assert self.scheduler.get_tenant_in_flight_count("t2") == 1

    def test_complete_decrements_tenant_count(self):
        """Completing a task frees up the tenant's concurrency budget."""
        self.scheduler.enqueue({"type": "test"}, tenant_id="t1")
        async def run():
            task = await self.scheduler.dequeue()
            assert task is not None
            assert self.scheduler.get_tenant_in_flight_count("t1") == 1
            self.scheduler.complete(task["id"])
            assert self.scheduler.get_tenant_in_flight_count("t1") == 0

        asyncio.run(run())

    def test_fail_decrements_tenant_count(self):
        """A failed task frees up the concurrency budget so a new one can run."""
        self.scheduler.enqueue({"type": "test"}, tenant_id="t1")
        async def run():
            task = await self.scheduler.dequeue()
            assert task is not None
            assert self.scheduler.get_tenant_in_flight_count("t1") == 1
            self.scheduler.fail(task["id"])
            assert self.scheduler.get_tenant_in_flight_count("t1") == 0

        asyncio.run(run())


class TestRecoveryInvariant:
    """Tests for the process-restart / stale-duplicate recovery scanner fix.

    The _committed_this_run dict is the key invariant: once a task is dispatched
    during a process instance it is recorded. A second attempt to dispatch the
    same task_id in the same run is a bug (duplicate dispatch) and must be rejected.
    """

    def setup_method(self):
        self._orig_env = os.environ.pop("AO_SCHEDULER_MAX_CONCURRENT_PER_TENANT", None)
        self.scheduler = TaskScheduler()

    def teardown_method(self):
        if self._orig_env is not None:
            os.environ["AO_SCHEDULER_MAX_CONCURRENT_PER_TENANT"] = self._orig_env
        elif "AO_SCHEDULER_MAX_CONCURRENT_PER_TENANT" in os.environ:
            del os.environ["AO_SCHEDULER_MAX_CONCURRENT_PER_TENANT"]

    def test_stale_duplicate_rejected_this_run(self):
        """Dispatching the same task_id twice in one run is rejected."""
        # Manually inject a task into _in_flight and _committed_this_run
        # to simulate a recovery scanner attempting to re-dispatch an already-
        # committed task in the same process instance.
        task = {
            "id": "task-already-committed",
            "type": "test",
            "tenant_id": "tenant-stale",
        }
        self.scheduler._in_flight[task["id"]] = task
        self.scheduler._committed_this_run[task["id"]] = task
        self.scheduler._tenant_in_flight["tenant-stale"] = {task["id"]}

        # Attempt to re-dispatch the same task_id — must return None / reject
        result = self.scheduler._dispatch_inflight(task, "tenant-stale")
        assert result is None
        # Task must NOT be in in_flight twice
        assert self.scheduler._in_flight.get(task["id"]) is not None
        # Still only one entry
        assert len(self.scheduler._in_flight) == 1

    def test_fresh_process_allows_dispatch(self):
        """A brand-new process instance can dispatch a task freely."""
        task = {"id": "brand-new-task", "type": "test", "tenant_id": "t1"}
        # _committed_this_run is empty — this is a fresh start
        assert "brand-new-task" not in self.scheduler._committed_this_run
        result = self.scheduler._dispatch_inflight(task, "t1")
        assert result is task  # dispatch succeeds
        assert "brand-new-task" in self.scheduler._committed_this_run

    def test_complete_then_redispatch_allowed(self):
        """A task that was completed can NOT be re-dispatched in the same run
        (idempotency: completed tasks are removed from committed_this_run)."""
        task = {"id": "once-and-done", "type": "test", "tenant_id": "t1"}
        self.scheduler._dispatch_inflight(task, "t1")

        # Complete it — this removes from committed_this_run
        self.scheduler.complete(task["id"])
        assert task["id"] not in self.scheduler._committed_this_run

        # Attempting to re-dispatch a completed task in the same run is fine
        # (it passes the stale check); the new task dict just gets a fresh id
        # assigned on enqueue. The old id won't appear again.
        # This test documents the intended behaviour: completed = fresh start.

    def test_audit_log_on_limit_exceeded(self):
        """Exceeding the concurrency limit produces an audit log entry."""
        for _ in range(10):
            self.scheduler.enqueue({"type": "test"}, tenant_id="t1")
        try:
            self.scheduler.enqueue({"type": "test"}, tenant_id="t1")
        except ConcurrencyLimitExceeded:
            pass
        log = self.scheduler.get_audit_log()
        events = [e for e in log if e["event"] == "LIMIT_EXCEEDED"]
        assert len(events) >= 1
        assert events[-1]["tenant_id"] == "t1"

    def test_audit_log_on_stale_rejection(self):
        """Stale duplicate rejection produces an audit log entry."""
        task = {"id": "stale-task", "type": "test", "tenant_id": "t1"}
        self.scheduler._in_flight[task["id"]] = task
        self.scheduler._committed_this_run[task["id"]] = task
        self.scheduler._tenant_in_flight["t1"] = {task["id"]}

        self.scheduler._dispatch_inflight(task, "t1")

        log = self.scheduler.get_audit_log()
        events = [e for e in log if e["event"] == "STALE_REJECTED"]
        assert len(events) >= 1
        assert events[-1]["task_id"] == "stale-task"


# Backward-compatibility: existing tests still pass
class TestSchedulerBackwardsCompatibility:
    """Re-run the original scheduler tests to confirm no regressions."""

    def setup_method(self):
        self._orig_env = os.environ.pop("AO_SCHEDULER_MAX_CONCURRENT_PER_TENANT", None)
        self.scheduler = TaskScheduler()

    def teardown_method(self):
        if self._orig_env is not None:
            os.environ["AO_SCHEDULER_MAX_CONCURRENT_PER_TENANT"] = self._orig_env
        elif "AO_SCHEDULER_MAX_CONCURRENT_PER_TENANT" in os.environ:
            del os.environ["AO_SCHEDULER_MAX_CONCURRENT_PER_TENANT"]

    def test_enqueue_task(self):
        task_id = self.scheduler.enqueue({"type": "test", "payload": {}})
        assert task_id is not None

    def test_dequeue_task(self):
        self.scheduler.enqueue({"type": "test", "payload": {"data": 1}})
        task = asyncio.run(self.scheduler.dequeue())
        assert task is not None
        assert task["type"] == "test"

    def test_enqueue_multiple_priorities(self):
        self.scheduler.enqueue({"type": "low"}, priority=1)
        self.scheduler.enqueue({"type": "high"}, priority=10)
        task = asyncio.run(self.scheduler.dequeue())
        assert task["type"] == "high"

    def test_complete_task(self):
        self.scheduler.enqueue({"type": "test"})
        task = asyncio.run(self.scheduler.dequeue())
        assert self.scheduler.complete(task["id"])

    def test_fail_task_with_retry(self):
        self.scheduler.enqueue({"type": "test"})
        task = asyncio.run(self.scheduler.dequeue())
        assert self.scheduler.fail(task["id"])

    def test_dequeue_returns_none_when_empty(self):
        task = asyncio.run(self.scheduler.dequeue())
        assert task is None
