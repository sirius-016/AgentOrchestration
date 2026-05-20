"""Tests for ETag-based optimistic locking."""
import pytest
from src.agent.registry import AgentRegistry


def test_etag_generation():
    """Test that agents get ETags on creation."""
    registry = AgentRegistry()
    agent_id = registry.register("test-agent", "test.type")
    
    agent, etag = registry.get_with_etag(agent_id)
    assert etag is not None
    assert len(etag) == 36  # UUID format


def test_update_with_valid_etag():
    """Test that updates with valid ETag succeed."""
    registry = AgentRegistry()
    agent_id = registry.register("test-agent", "test.type")
    
    agent, etag = registry.get_with_etag(agent_id)
    success, new_etag = registry.update_with_etag(agent_id, {"config": {"new": "value"}}, etag)
    
    assert success
    assert new_etag != etag  # ETag should change after update


def test_update_with_stale_etag():
    """Test that updates with stale ETag fail."""
    registry = AgentRegistry()
    agent_id = registry.register("test-agent", "test.type")
    
    # First update
    agent, etag1 = registry.get_with_etag(agent_id)
    registry.update_with_etag(agent_id, {"config": {"v": 1}}, etag1)
    
    # Second update with old ETag should fail
    success, current_etag = registry.update_with_etag(agent_id, {"config": {"v": 2}}, etag1)
    
    assert not success
    assert current_etag != etag1  # Returns current ETag


def test_update_nonexistent_agent():
    """Test that updating nonexistent agent fails."""
    registry = AgentRegistry()
    success, etag = registry.update_with_etag("nonexistent", {}, "any-etag")
    assert not success
    assert etag is None
