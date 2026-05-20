"""Tests for execution cancellation result storage."""
import pytest
from src.agent.executor import AgentExecutor, ExecutionResult


def test_cancel_stores_result():
    """Test that cancellation stores a CANCELLED result."""
    executor = AgentExecutor()
    exec_id = executor.execute("test-agent", {"task": "sleep 1"})
    
    result = executor.cancel(exec_id)
    assert result is True
    
    # Check result is stored
    stored = executor.get_result(exec_id)
    assert stored is not None
    assert stored.get("cancelled") is True or stored.get("result") == ExecutionResult.CANCELLED.value


def test_cancel_nonexistent():
    """Test that cancelling nonexistent execution returns False."""
    executor = AgentExecutor()
    assert executor.cancel("nonexistent-id") is False
