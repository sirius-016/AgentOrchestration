"""Tests for reserved environment key protection."""
import pytest
from src.agent.runtime import AgentRuntime


def test_reserved_env_key_rejected():
    """Test that reserved env keys cannot be overridden."""
    runtime = AgentRuntime()
    runtime.config["env"] = {"AO_RUNTIME_MODE": "privileged"}
    
    with pytest.raises(ValueError, match="reserved environment"):
        runtime.start()


def test_non_reserved_env_allowed():
    """Test that non-reserved env keys work fine."""
    runtime = AgentRuntime()
    runtime.config["env"] = {"MY_CUSTOM_VAR": "value"}
    # Should not raise
    try:
        runtime.start()
    except Exception as e:
        # We may get other errors, but not the reserved key error
        assert "reserved" not in str(e).lower()
