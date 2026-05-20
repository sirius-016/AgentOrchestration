"""Tests for handler pinning in agent registry."""
import pytest
from src.agent.registry import AgentRegistry, AgentStatus


def test_pin_handler():
    """Test that handlers can be pinned to agents."""
    registry = AgentRegistry()
    agent_id = registry.register("test-agent", "test.type")
    
    assert registry.pin_handler(agent_id, "handler-123")
    assert registry.get_pinned_handler(agent_id) == "handler-123"


def test_unpin_handler():
    """Test that handler pins can be removed."""
    registry = AgentRegistry()
    agent_id = registry.register("test-agent", "test.type")
    
    registry.pin_handler(agent_id, "handler-123")
    assert registry.unpin_handler(agent_id)
    assert registry.get_pinned_handler(agent_id) is None


def test_pin_nonexistent_agent():
    """Test that pinning to nonexistent agent fails."""
    registry = AgentRegistry()
    assert not registry.pin_handler("nonexistent", "handler-123")


def test_multiple_pins():
    """Test that re-pinning overwrites previous pin."""
    registry = AgentRegistry()
    agent_id = registry.register("test-agent", "test.type")
    
    registry.pin_handler(agent_id, "handler-123")
    registry.pin_handler(agent_id, "handler-456")
    
    assert registry.get_pinned_handler(agent_id) == "handler-456"
