"""Tests for queue capacity rollback on transaction failure."""
import pytest
from src.orchestrator.scheduler import TaskScheduler


def test_capacity_increases_on_enqueue():
    """Test that enqueue increases used capacity."""
    ts = TaskScheduler(max_capacity=10)
    task_id = ts.enqueue({"data": "test"})
    
    cap = ts.get_capacity()
    assert cap["used"] == 1
    assert cap["available"] == 9


def test_capacity_released_on_rollback():
    """Test that rollback_enqueue releases capacity."""
    ts = TaskScheduler(max_capacity=10)
    task_id = ts.enqueue({"data": "test"})
    
    ts.rollback_enqueue(task_id)
    
    cap = ts.get_capacity()
    assert cap["used"] == 0


def test_capacity_at_limit_raises():
    """Test that enqueue raises when at capacity."""
    ts = TaskScheduler(max_capacity=2)
    ts.enqueue({"data": "a"})
    ts.enqueue({"data": "b"})
    
    with pytest.raises(RuntimeError, match="capacity"):
        ts.enqueue({"data": "c"})


def test_permanent_failure_releases_capacity():
    """Test that permanently failed tasks release capacity."""
    ts = TaskScheduler(max_capacity=10)
    task_id = ts.enqueue({"data": "test"}, priority=0)
    
    # Simulate dequeue
    ts._in_flight[task_id] = ts._scheduled.get(task_id) or {"id": task_id}
    
    # Permanently fail (max_retries exceeded)
    ts.fail(task_id)
    ts.fail(task_id)
    ts.fail(task_id)
    ts.fail(task_id)  # 4th fail = permanent
    
    cap = ts.get_capacity()
    assert cap["used"] == 0


def test_release_capacity():
    """Test release_capacity frees all slots."""
    ts = TaskScheduler(max_capacity=10)
    for i in range(5):
        ts.enqueue({"data": f"t{i}"})
    
    freed = ts.release_capacity()
    assert freed == 5
    assert ts.get_capacity()["used"] == 0
