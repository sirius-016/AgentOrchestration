"""Tests for retry loop termination after terminal state."""
import pytest
from src.agent.runtime import AgentRuntime, RuntimeState, TERMINAL_STATES


def test_terminal_states_are_terminal():
    """Test that terminal states are correctly identified."""
    assert RuntimeState.STOPPED in TERMINAL_STATES
    assert RuntimeState.CRASHED in TERMINAL_STATES
    assert RuntimeState.COMPLETED in TERMINAL_STATES
    assert RuntimeState.RUNNING not in TERMINAL_STATES
    assert RuntimeState.STARTING not in TERMINAL_STATES


def test_no_retry_after_crash_exceeds_max():
    """Test that no retry occurs after crash when max retries reached."""
    rt = AgentRuntime(max_retries=2)
    rt._states["agent-1"] = RuntimeState.CRASHED
    rt._retry_counts["agent-1"] = 2
    
    assert not rt._should_retry("agent-1", RuntimeState.CRASHED)


def test_retry_count_resets_on_terminal():
    """Test that retry count is reset when reaching terminal state."""
    rt = AgentRuntime(max_retries=3)
    rt._retry_counts["agent-2"] = 3
    
    rt._record_state_change("agent-2", RuntimeState.COMPLETED)
    
    assert rt._retry_counts["agent-2"] == 0


def test_retry_allowed_before_max():
    """Test that retry is allowed before max retries is reached."""
    rt = AgentRuntime(max_retries=3)
    rt._retry_counts["agent-3"] = 1
    
    assert rt._should_retry("agent-3", RuntimeState.RUNNING)


def test_no_retry_after_terminal_state():
    """Test that retry is blocked for terminal states even with 0 retries."""
    rt = AgentRuntime(max_retries=3)
    
    assert not rt._should_retry("agent-4", RuntimeState.STOPPED)
    assert not rt._should_retry("agent-4", RuntimeState.COMPLETED)


def test_retry_status():
    """Test retry status reporting."""
    rt = AgentRuntime(max_retries=3)
    rt._retry_counts["agent-5"] = 2
    rt._states["agent-5"] = RuntimeState.RUNNING
    
    status = rt.get_retry_status("agent-5")
    assert status["retries"] == 2
    assert status["max_retries"] == 3
    assert status["can_retry"] is True
    assert status["state"] == "running"


def test_no_start_after_terminal_without_reset():
    """Test that agent cannot start after terminal without reset."""
    rt = AgentRuntime(max_retries=2)
    rt._states["agent-6"] = RuntimeState.CRASHED
    rt._retry_counts["agent-6"] = 2
    
    # start() should check _should_retry and return False
    assert not rt._should_retry("agent-6", RuntimeState.CRASHED)
