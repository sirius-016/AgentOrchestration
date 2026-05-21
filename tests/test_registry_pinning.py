"""Tests for handler pinning functionality in AgentRegistry.

Tests for Issue #31: Pin resolved handler per attempt
https://github.com/orchestration-agent/AgentOrchestration/issues/31
"""

import pytest
import uuid
from src.agent.registry import (
    AgentRegistry,
    AgentStatus,
    HandlerResolutionError,
    InFlightError,
)


class TestHandlerPinning:
    """Test suite for handler pinning invariant enforcement."""
    
    def setup_method(self):
        """Create a fresh registry for each test."""
        self.registry = AgentRegistry()
    
    def test_resolve_handler_pins_handler(self):
        """Test that resolve_handler pins and returns a handler."""
        agent_id = self.registry.register("test-agent", "worker", {"handler_id": "handler-1"})
        attempt_id = str(uuid.uuid4())
        
        handler = self.registry.resolve_handler(agent_id, attempt_id)
        
        assert handler == "handler-1"
        assert self.registry.is_handler_pinned(attempt_id)
        assert self.registry.get_pinned_handler(attempt_id) == "handler-1"
    
    def test_resolve_handler_returns_same_pinned_handler(self):
        """Test that resolving the same attempt returns the cached handler."""
        agent_id = self.registry.register("test-agent", "worker", {"handler_id": "handler-1"})
        attempt_id = str(uuid.uuid4())
        
        handler1 = self.registry.resolve_handler(agent_id, attempt_id)
        handler2 = self.registry.resolve_handler(agent_id, attempt_id)
        
        assert handler1 == handler2
        assert handler1 == "handler-1"
    
    def test_default_handler_resolution(self):
        """Test default handler resolution based on agent type."""
        agent_id = self.registry.register("test-agent", "worker.special", {})
        attempt_id = str(uuid.uuid4())
        
        handler = self.registry.resolve_handler(agent_id, attempt_id)
        
        assert handler == "handler-worker.special"
    
    def test_custom_handler_resolver(self):
        """Test using a custom handler resolver function."""
        agent_id = self.registry.register("test-agent", "worker", {})
        attempt_id = str(uuid.uuid4())
        
        def custom_resolver(aid, agent_data):
            return f"custom-{agent_data['name']}"
        
        handler = self.registry.resolve_handler(agent_id, attempt_id, handler_resolver=custom_resolver)
        
        assert handler == "custom-test-agent"
    
    def test_release_handler(self):
        """Test releasing a handler after attempt completion."""
        agent_id = self.registry.register("test-agent", "worker", {"handler_id": "handler-1"})
        attempt_id = str(uuid.uuid4())
        
        self.registry.resolve_handler(agent_id, attempt_id)
        assert self.registry.is_handler_pinned(attempt_id)
        
        result = self.registry.release_handler(attempt_id, agent_id)
        
        assert result is True
        assert not self.registry.is_handler_pinned(attempt_id)
        assert agent_id not in self.registry._in_flight_agents
    
    def test_delete_in_flight_agent_raises_error(self):
        """Test that deleting an agent with pinned handlers raises InFlightError."""
        agent_id = self.registry.register("test-agent", "worker", {"handler_id": "handler-1"})
        attempt_id = str(uuid.uuid4())
        
        self.registry.resolve_handler(agent_id, attempt_id)
        
        with pytest.raises(InFlightError) as exc_info:
            self.registry.delete(agent_id)
        
        assert "in-flight" in str(exc_info.value).lower()
    
    def test_update_config_with_different_handler_raises_error(self):
        """Test that changing handler config mid-flight raises InFlightError."""
        agent_id = self.registry.register("test-agent", "worker", {"handler_id": "handler-1"})
        attempt_id = str(uuid.uuid4())
        
        self.registry.resolve_handler(agent_id, attempt_id)
        
        with pytest.raises(InFlightError) as exc_info:
            self.registry.update_agent_config(agent_id, {"handler_id": "handler-2"})
        
        assert "handler" in str(exc_info.value).lower()
    
    def test_update_config_with_same_handler_succeeds(self):
        """Test that config updates with same handler are allowed."""
        agent_id = self.registry.register("test-agent", "worker", {"handler_id": "handler-1"})
        attempt_id = str(uuid.uuid4())
        
        self.registry.resolve_handler(agent_id, attempt_id)
        
        result = self.registry.update_agent_config(agent_id, {"other_setting": "value"})
        
        assert result is True
    
    def test_update_agent_config_after_release(self):
        """Test that config updates work after handler is released."""
        agent_id = self.registry.register("test-agent", "worker", {"handler_id": "handler-1"})
        attempt_id = str(uuid.uuid4())
        
        self.registry.resolve_handler(agent_id, attempt_id)
        self.registry.release_handler(attempt_id, agent_id)
        
        result = self.registry.update_agent_config(agent_id, {"handler_id": "handler-2"})
        
        assert result is True
        assert self.registry.get(agent_id)["config"]["handler_id"] == "handler-2"
    
    def test_invalidate_cache_marks_for_invalidation(self):
        """Test that invalidate_cache marks agent for next-resolution invalidation."""
        agent_id = self.registry.register("test-agent", "worker", {})
        
        result = self.registry.invalidate_cache(agent_id)
        
        assert result is True
        assert agent_id in self.registry._cache_invalidations
    
    def test_invalidate_cache_force_raises_error_when_in_flight(self):
        """Test that force invalidation raises error when handlers are pinned."""
        agent_id = self.registry.register("test-agent", "worker", {"handler_id": "handler-1"})
        attempt_id = str(uuid.uuid4())
        
        self.registry.resolve_handler(agent_id, attempt_id)
        
        with pytest.raises(InFlightError):
            self.registry.invalidate_cache(agent_id, force=True)
    
    def test_get_in_flight_attempts(self):
        """Test retrieving all in-flight attempts for an agent."""
        agent_id = self.registry.register("test-agent", "worker", {})
        attempt1 = str(uuid.uuid4())
        attempt2 = str(uuid.uuid4())
        
        self.registry.resolve_handler(agent_id, attempt1)
        self.registry.resolve_handler(agent_id, attempt2)
        
        in_flight = self.registry.get_in_flight_attempts(agent_id)
        
        assert len(in_flight) == 2
        assert attempt1 in in_flight
        assert attempt2 in in_flight
    
    def test_has_pinned_handlers(self):
        """Test checking if an agent has pinned handlers."""
        agent_id = self.registry.register("test-agent", "worker", {})
        attempt_id = str(uuid.uuid4())
        
        assert not self.registry._has_pinned_handlers(agent_id)
        
        self.registry.resolve_handler(agent_id, attempt_id)
        
        assert self.registry._has_pinned_handlers(agent_id)
    
    def test_get_handler_stats(self):
        """Test retrieving handler pinning statistics."""
        agent_id = self.registry.register("test-agent", "worker", {"handler_id": "handler-1"})
        attempt1 = str(uuid.uuid4())
        attempt2 = str(uuid.uuid4())
        
        self.registry.resolve_handler(agent_id, attempt1)
        self.registry.resolve_handler(agent_id, attempt2)
        
        stats = self.registry.get_handler_stats()
        
        assert stats["total_pinned_handlers"] == 2
        assert stats["agents_with_in_flight_attempts"] == 1
        assert stats["in_flight_breakdown"][agent_id] == 2
    
    def test_resolve_handler_for_nonexistent_agent_raises_error(self):
        """Test that resolving for a non-existent agent raises HandlerResolutionError."""
        attempt_id = str(uuid.uuid4())
        
        with pytest.raises(HandlerResolutionError):
            self.registry.resolve_handler("nonexistent", attempt_id)
    
    def test_multiple_agents_separate_pin_tracking(self):
        """Test that multiple agents have separate pin tracking."""
        agent1 = self.registry.register("agent-1", "worker", {"handler_id": "handler-1"})
        agent2 = self.registry.register("agent-2", "worker", {"handler_id": "handler-2"})
        attempt1 = str(uuid.uuid4())
        attempt2 = str(uuid.uuid4())
        
        handler1 = self.registry.resolve_handler(agent1, attempt1)
        handler2 = self.registry.resolve_handler(agent2, attempt2)
        
        assert handler1 == "handler-1"
        assert handler2 == "handler-2"
        assert self.registry.get_pinned_handler(attempt1) == "handler-1"
        assert self.registry.get_pinned_handler(attempt2) == "handler-2"
    
    def test_delete_nonexistent_agent_returns_false(self):
        """Test that deleting a non-existent agent returns False."""
        result = self.registry.delete("nonexistent")
        assert result is False
    
    def test_release_nonexistent_handler_returns_false(self):
        """Test that releasing a non-existent handler returns False."""
        result = self.registry.release_handler("nonexistent-attempt")
        assert result is False
    
    def test_invalidate_cache_nonexistent_agent_returns_false(self):
        """Test that invalidating cache for non-existent agent returns False."""
        result = self.registry.invalidate_cache("nonexistent")
        assert result is False
    
    def test_update_agent_config_nonexistent_agent_returns_false(self):
        """Test that updating config for non-existent agent returns False."""
        result = self.registry.update_agent_config("nonexistent", {"key": "value"})
        assert result is False


class TestHandlerPinningIntegration:
    """Integration tests simulating real-world scenarios."""
    
    def setup_method(self):
        """Create a fresh registry for each test."""
        self.registry = AgentRegistry()
    
    def test_full_task_lifecycle(self):
        """Test a complete task lifecycle with handler pinning."""
        # Register agent
        agent_id = self.registry.register("task-agent", "worker", {"handler_id": "handler-v1"})
        
        # Start task - resolve handler
        attempt_id = str(uuid.uuid4())
        handler = self.registry.resolve_handler(agent_id, attempt_id)
        assert handler == "handler-v1"
        
        # Simulate config change mid-flight (should fail)
        with pytest.raises(InFlightError):
            self.registry.update_agent_config(agent_id, {"handler_id": "handler-v2"})
        
        # Complete task - release handler
        self.registry.release_handler(attempt_id, agent_id)
        
        # Now config change should succeed
        result = self.registry.update_agent_config(agent_id, {"handler_id": "handler-v2"})
        assert result is True
        
        # Next task gets new handler
        attempt_id2 = str(uuid.uuid4())
        handler2 = self.registry.resolve_handler(agent_id, attempt_id2)
        assert handler2 == "handler-v2"
    
    def test_concurrent_attempts_same_agent(self):
        """Test multiple concurrent attempts for the same agent."""
        agent_id = self.registry.register("concurrent-agent", "worker", {"handler_id": "handler-1"})
        
        # Start multiple attempts
        attempts = [str(uuid.uuid4()) for _ in range(5)]
        handlers = []
        
        for attempt_id in attempts:
            handler = self.registry.resolve_handler(agent_id, attempt_id)
            handlers.append(handler)
        
        # All should have the same handler
        assert all(h == "handler-1" for h in handlers)
        
        # All should be in-flight
        in_flight = self.registry.get_in_flight_attempts(agent_id)
        assert len(in_flight) == 5
        
        # Complete all attempts
        for attempt_id in attempts:
            self.registry.release_handler(attempt_id, agent_id)
        
        # No more in-flight
        assert not self.registry._has_pinned_handlers(agent_id)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])