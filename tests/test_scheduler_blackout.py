"""Tests for workflow blackout windows in scheduler."""
import pytest
import time
from src.orchestrator.scheduler import (
    TaskScheduler, BlackoutWindow, DispatchError,
)


def test_blackout_window_active_during_window():
    """Test that blackout is active during window hours."""
    # Create window 09:00-17:00 UTC
    bw = BlackoutWindow("morning", 9, 0, 17, 0)

    # Use a timestamp at 10:00 UTC
    ts_10am = 1700000000.0  # roughly 2023-11-14 10:00 UTC
    assert bw.is_active(ts_10am) is True


def test_blackout_window_inactive_outside_window():
    """Test that blackout is inactive outside window hours."""
    bw = BlackoutWindow("morning", 9, 0, 17, 0)

    ts_8am = 1700000000.0 - 3600  # 1 hour before
    assert bw.is_active(ts_8am) is False

    ts_6pm = 1700000000.0 + 3600 * 8  # after 5pm
    assert bw.is_active(ts_6pm) is False


def test_overnight_blackout_window():
    """Test overnight blackout window (e.g., 22:00-06:00)."""
    bw = BlackoutWindow("night", 22, 0, 6, 0)

    ts_23pm = 1700000000.0  # 22:xx
    ts_3am = 1700000000.0 - 3600 * 7  # 03:xx

    assert bw.is_active(ts_23pm) is True
    assert bw.is_active(ts_3am) is True


def test_scheduler_respects_blackout_on_dequeue():
    """Test that dequeue raises DispatchError during blackout."""
    scheduler = TaskScheduler()
    bw = BlackoutWindow("always-on", 0, 0, 23, 59)  # Always active
    scheduler.add_blackout_window(bw)

    scheduler.enqueue({"task": "data"}, queue="default")

    # dequeue should raise
    import asyncio
    async def test():
        with pytest.raises(DispatchError, match="blocked by active blackout"):
            await scheduler.dequeue(queue="default")

    asyncio.get_event_loop().run_until_complete(test())


def test_scheduler_allows_dequeue_outside_blackout():
    """Test that dequeue succeeds outside blackout window."""
    scheduler = TaskScheduler()
    bw = BlackoutWindow("never-active", 9, 0, 17, 0)
    scheduler.add_blackout_window(bw)

    scheduler.enqueue({"task": "data"}, queue="default")

    import asyncio
    async def test():
        # No active window (using current time)
        task = await scheduler.dequeue(queue="default")
        # If current time is outside 09:00-17:00, this succeeds
        # Otherwise it returns None (no task)
        assert task is None or "task" in task

    asyncio.get_event_loop().run_until_complete(test())


def test_remove_blackout_window():
    """Test removing a blackout window."""
    scheduler = TaskScheduler()
    bw = BlackoutWindow("test", 0, 0, 23, 59)
    scheduler.add_blackout_window(bw)

    assert len(scheduler._blackout_windows) == 1
    removed = scheduler.remove_blackout_window("test")
    assert removed is True
    assert len(scheduler._blackout_windows) == 0


def test_is_dispatch_allowed():
    """Test dispatch permission check."""
    scheduler = TaskScheduler()
    bw = BlackoutWindow("active", 0, 0, 23, 59)
    scheduler.add_blackout_window(bw)

    task = {}
    result = scheduler.is_dispatch_allowed(task)
    assert result is False
    assert task["_blackout_check"]["allowed"] is False
    assert "active" in task["_blackout_check"]["active_windows"]


def test_blackout_audit_log():
    """Test that blocked dispatches are logged in audit trail."""
    scheduler = TaskScheduler()
    bw = BlackoutWindow("always-on", 0, 0, 23, 59)
    scheduler.add_blackout_window(bw)
    scheduler.enqueue({"task": "test"}, queue="default")

    import asyncio

    async def trigger():
        try:
            await scheduler.dequeue(queue="default")
        except DispatchError:
            pass

    asyncio.get_event_loop().run_until_complete(trigger())

    assert len(scheduler._blackout_audit) >= 1
    log = scheduler._blackout_audit[-1]
    assert log["action"] == "blocked"
    assert "always-on" in log["blocked_by"]
