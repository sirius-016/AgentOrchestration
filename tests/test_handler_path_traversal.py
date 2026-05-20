"""Tests for handler name path traversal prevention."""
import pytest
from src.agent.registry import AgentRegistry


def test_path_traversal_in_name_rejected():
    """Test that path traversal in handler names is rejected."""
    registry = AgentRegistry()
    with pytest.raises(ValueError, match="path traversal"):
        registry.register("../etc/passwd", "test.type")


def test_trailing_slash_rejected():
    """Test that paths starting with / are rejected."""
    registry = AgentRegistry()
    with pytest.raises(ValueError, match="path traversal"):
        registry.register("/etc/passwd", "test.type")


def test_backslash_path_rejected():
    """Test that backslash paths are rejected."""
    registry = AgentRegistry()
    with pytest.raises(ValueError, match="path traversal"):
        registry.register("..\\..\\windows\\system32", "test.type")


def test_valid_name_accepted():
    """Test that valid handler names work."""
    registry = AgentRegistry()
    agent_id = registry.register("my-agent", "test.type")
    assert agent_id is not None


def test_dotted_name_accepted():
    """Test that dotted names (like python modules) are accepted."""
    registry = AgentRegistry()
    agent_id = registry.register("my.agent.module", "test.type")
    assert agent_id is not None
