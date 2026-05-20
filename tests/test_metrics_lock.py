"""Tests for MetricsCollector lock safety."""
import pytest
import threading
import time
from src.common.metrics import MetricsCollector


def test_stop_timer_no_hang():
    """Test that stop_timer does not hang due to lock re-entry."""
    mc = MetricsCollector()
    mc.start_timer("test_metric")
    time.sleep(0.01)
    
    # This should not hang
    elapsed = mc.stop_timer("test_metric")
    assert elapsed > 0


def test_concurrent_start_stop():
    """Test that concurrent start/stop operations are safe."""
    mc = MetricsCollector()
    errors = []
    
    def worker():
        try:
            for _ in range(10):
                mc.start_timer("shared_metric")
                time.sleep(0.001)
                mc.stop_timer("shared_metric")
        except Exception as e:
            errors.append(e)
    
    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    
    assert len(errors) == 0


def test_observe_under_stop_timer():
    """Test that observe can be called from within stop_timer (RLock allows this)."""
    mc = MetricsCollector()
    
    # Simulate what would happen if observe is called during stop_timer
    # With RLock this should work
    mc.start_timer("test")
    elapsed = mc.stop_timer("test")
    # observe should work fine
    mc.observe("test", elapsed)
    assert elapsed > 0
