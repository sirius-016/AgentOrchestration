"""Tests for execution cancellation result storage."""
import pytest
from src.agent.executor import AgentExecutor, ExecutionResult


def test_cancel_stores_result():
    """Test that cancellation stores a CANCELLED result."""
    executor = AgentExecutor()
    exec_id = executor.execute("test-agent", {"task": "sleep 1"})
    
    result = executor.cancel(exec_id)
    assert result is True
    
    execution = executor.get(exec_id)
    assert execution["status"] == "cancelled"
    assert execution["result"] == ExecutionResult.CANCELLED.value


def test_cancel_nonexistent():
    """Test that cancelling nonexistent execution returns False."""
    executor = AgentExecutor()
    assert executor.cancel("nonexistent-id") is False


def test_execution_status_after_cancel():
    """Test execution has updated_at after cancellation."""
    executor = AgentExecutor()
    exec_id = executor.execute("test-agent", {"task": "sleep 1"})
    
    before = executor.get(exec_id)["updated_at"]
    executor.cancel(exec_id)
    after = executor.get(exec_id)["updated_at"]
    
    assert after >= before
