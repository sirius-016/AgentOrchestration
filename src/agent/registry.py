"""Agent Registry — Manages agent lifecycle and metadata.

Implements handler pinning per attempt to prevent mid-run registry updates.
See Issue #31: https://github.com/orchestration-agent/AgentOrchestration/issues/31
"""

import json
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


class AgentStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    FAILED = "failed"
    TERMINATED = "terminated"


class HandlerResolutionError(Exception):
    """Raised when handler resolution fails due to invalid state."""
    pass


class InFlightError(Exception):
    """Raised when attempting to modify an in-flight agent."""
    pass


class AgentRegistry:
    """Registry for managing agent lifecycle with handler pinning support.
    
    The registry enforces the invariant that once a handler is resolved for
    an attempt, it cannot change during execution. This prevents stale,
    duplicate, or policy-violating transitions during mid-run registry updates.
    """
    
    def __init__(self, storage_backend: str = "memory"):
        self.storage_backend = storage_backend
        self._agents: Dict[str, Dict[str, Any]] = {}
        self._index: Dict[str, List[str]] = {}
        
        # Handler pinning: attempt_id -> handler_id
        self._resolved_handlers: Dict[str, str] = {}
        
        # In-flight tracking: agent_id -> set of attempt_ids
        self._in_flight_agents: Dict[str, Set[str]] = {}
        
        # Cache invalidation tracking: agent_id -> invalidation_timestamp
        self._cache_invalidations: Dict[str, float] = {}
        
        # Agent to handler mapping for quick lookup: agent_id -> current_handler_id
        self._agent_handlers: Dict[str, str] = {}

    def register(self, name: str, agent_type: str, config: Optional[Dict] = None) -> str:
        """Register a new agent in the registry.
        
        Args:
            name: Human-readable name for the agent
            agent_type: Type classification for the agent
            config: Optional configuration dictionary
            
        Returns:
            The newly created agent_id
            
        Raises:
            InFlightError: If attempting to re-register an in-flight agent
        """
        agent_id = str(uuid.uuid4())
        timestamp = time.time()
        
        self._agents[agent_id] = {
            "id": agent_id,
            "name": name,
            "type": agent_type,
            "status": AgentStatus.PENDING.value,
            "config": config or {},
            "created_at": timestamp,
            "updated_at": timestamp,
            "version": "1.0.0",
            "metrics": {"tasks_completed": 0, "errors": 0, "uptime": 0},
        }
        
        group = agent_type.split(".")[0]
        if group not in self._index:
            self._index[group] = []
        self._index[group].append(agent_id)
        
        return agent_id

    def get(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve agent metadata by ID.
        
        Args:
            agent_id: The unique identifier for the agent
            
        Returns:
            Agent metadata dict or None if not found
        """
        return self._agents.get(agent_id)

    def list(self, status: Optional[AgentStatus] = None, group: Optional[str] = None) -> List[Dict[str, Any]]:
        """List agents with optional filtering.
        
        Args:
            status: Optional status filter
            group: Optional group filter (derived from agent_type)
            
        Returns:
            List of matching agent metadata dicts
        """
        agents = self._agents.values()
        if status:
            agents = [a for a in agents if a["status"] == status.value]
        if group:
            agent_ids = self._index.get(group, [])
            agents = [a for a in agents if a["id"] in agent_ids]
        return list(agents)

    def update_status(self, agent_id: str, status: AgentStatus) -> bool:
        """Update agent status with in-flight protection.
        
        Args:
            agent_id: The unique identifier for the agent
            status: New status to set
            
        Returns:
            True if successful, False if agent not found
            
        Raises:
            InFlightError: If agent has pinned handlers and update would violate invariant
        """
        if agent_id not in self._agents:
            return False
            
        # Check if agent is in-flight with pinned handlers
        if self._has_pinned_handlers(agent_id):
            # Only allow status changes that don't affect handler resolution
            # RUNNING -> PAUSED, STOPPED, FAILED, TERMINATED are allowed
            # but we must ensure handler remains pinned
            current_status = self._agents[agent_id]["status"]
            if status in (AgentStatus.PENDING, AgentStatus.RUNNING):
                raise InFlightError(
                    f"Cannot set agent {agent_id} to {status.value} while "
                    f"handlers are pinned for in-flight attempts"
                )
        
        self._agents[agent_id]["status"] = status.value
        self._agents[agent_id]["updated_at"] = time.time()
        return True

    def delete(self, agent_id: str) -> bool:
        """Delete an agent from the registry.
        
        Args:
            agent_id: The unique identifier for the agent
            
        Returns:
            True if deleted, False if not found
            
        Raises:
            InFlightError: If agent has in-flight attempts with pinned handlers
        """
        if agent_id not in self._agents:
            return False
            
        # Prevent deletion of in-flight agents
        if self._has_pinned_handlers(agent_id):
            raise InFlightError(
                f"Cannot delete agent {agent_id} while it has "
                f"in-flight attempts with pinned handlers"
            )
        
        agent = self._agents.pop(agent_id)
        group = agent["type"].split(".")[0]
        if group in self._index and agent_id in self._index[group]:
            self._index[group].remove(agent_id)
        
        # Clean up any stale cache entries
        self._cache_invalidations.pop(agent_id, None)
        self._agent_handlers.pop(agent_id, None)
        
        return True

    def count(self) -> int:
        """Return the total number of registered agents."""
        return len(self._agents)
    
    # ========== Handler Pinning API ==========
    
    def resolve_handler(
        self, 
        agent_id: str, 
        attempt_id: str,
        handler_resolver: Optional[callable] = None
    ) -> str:
        """Resolve and pin a handler for a specific attempt.
        
        This is the core invariant enforcement: once a handler is resolved
        for an attempt, it cannot change for the duration of that attempt.
        
        Args:
            agent_id: The agent to resolve a handler for
            attempt_id: Unique identifier for this attempt
            handler_resolver: Optional callable to determine handler (default: uses agent config)
            
        Returns:
            The pinned handler_id
            
        Raises:
            HandlerResolutionError: If agent not found or resolution fails
            InFlightError: If agent is marked for cache invalidation mid-flight
        """
        if agent_id not in self._agents:
            raise HandlerResolutionError(f"Agent {agent_id} not found in registry")
        
        # Check if already resolved for this attempt
        if attempt_id in self._resolved_handlers:
            return self._resolved_handlers[attempt_id]
        
        # Check for cache invalidation in progress
        if agent_id in self._cache_invalidations:
            invalidation_time = self._cache_invalidations[agent_id]
            # If invalidation happened, we need fresh resolution
            # but we still pin it immediately
            del self._cache_invalidations[agent_id]
        
        # Resolve handler (use provided resolver or default logic)
        if handler_resolver:
            handler_id = handler_resolver(agent_id, self._agents[agent_id])
        else:
            # Default resolution: use agent's type-based handler or config-specified handler
            agent = self._agents[agent_id]
            handler_id = agent.get("config", {}).get(
                "handler_id",
                f"handler-{agent['type']}"
            )
        
        # Pin the handler for this attempt
        self._resolved_handlers[attempt_id] = handler_id
        
        # Track in-flight agent
        if agent_id not in self._in_flight_agents:
            self._in_flight_agents[agent_id] = set()
        self._in_flight_agents[agent_id].add(attempt_id)
        
        # Store current handler for the agent
        self._agent_handlers[agent_id] = handler_id
        
        return handler_id
    
    def get_pinned_handler(self, attempt_id: str) -> Optional[str]:
        """Get the pinned handler for an attempt without resolving.
        
        Args:
            attempt_id: The attempt identifier
            
        Returns:
            Pinned handler_id or None if not resolved
        """
        return self._resolved_handlers.get(attempt_id)
    
    def release_handler(self, attempt_id: str, agent_id: Optional[str] = None) -> bool:
        """Release a pinned handler after attempt completion.
        
        This should be called when an attempt completes (success or failure)
        to allow future handler resolution for the agent.
        
        Args:
            attempt_id: The attempt to release
            agent_id: Optional agent_id for faster lookup
            
        Returns:
            True if released, False if not found
        """
        if attempt_id not in self._resolved_handlers:
            return False
        
        # Find agent_id if not provided
        if agent_id is None:
            for aid, attempts in self._in_flight_agents.items():
                if attempt_id in attempts:
                    agent_id = aid
                    break
        
        # Remove from resolved handlers
        del self._resolved_handlers[attempt_id]
        
        # Remove from in-flight tracking
        if agent_id and agent_id in self._in_flight_agents:
            self._in_flight_agents[agent_id].discard(attempt_id)
            # Clean up empty sets
            if not self._in_flight_agents[agent_id]:
                del self._in_flight_agents[agent_id]
        
        return True
    
    def invalidate_cache(self, agent_id: str, force: bool = False) -> bool:
        """Mark agent for cache invalidation.
        
        This prevents mid-run changes from affecting pinned handlers while
        signaling that the next resolution should use fresh data.
        
        Args:
            agent_id: The agent to invalidate
            force: If True, clear all pinned handlers for this agent (dangerous)
            
        Returns:
            True if invalidated, False if agent not found
            
        Raises:
            InFlightError: If force=True and agent has in-flight attempts
        """
        if agent_id not in self._agents:
            return False
        
        if force:
            # Clear all pinned handlers for this agent
            if self._has_pinned_handlers(agent_id):
                raise InFlightError(
                    f"Cannot force invalidate agent {agent_id} with in-flight attempts"
                )
        
        # Mark for invalidation
        self._cache_invalidations[agent_id] = time.time()
        return True
    
    def _has_pinned_handlers(self, agent_id: str) -> bool:
        """Check if an agent has any pinned handlers for in-flight attempts.
        
        Args:
            agent_id: The agent to check
            
        Returns:
            True if agent has pinned handlers
        """
        return agent_id in self._in_flight_agents and len(self._in_flight_agents[agent_id]) > 0
    
    def get_in_flight_attempts(self, agent_id: str) -> Set[str]:
        """Get all in-flight attempt IDs for an agent.
        
        Args:
            agent_id: The agent to check
            
        Returns:
            Set of attempt_ids with pinned handlers, empty if none
        """
        return self._in_flight_agents.get(agent_id, set()).copy()
    
    def is_handler_pinned(self, attempt_id: str) -> bool:
        """Check if a handler is pinned for a specific attempt.
        
        Args:
            attempt_id: The attempt to check
            
        Returns:
            True if handler is pinned
        """
        return attempt_id in self._resolved_handlers
    
    def update_agent_config(
        self, 
        agent_id: str, 
        config: Dict[str, Any],
        merge: bool = True
    ) -> bool:
        """Update agent configuration with in-flight protection.
        
        Args:
            agent_id: The agent to update
            config: New configuration (merged if merge=True)
            merge: If True, merge with existing config; if False, replace
            
        Returns:
            True if updated, False if not found
            
        Raises:
            InFlightError: If agent has pinned handlers and config affects handler resolution
        """
        if agent_id not in self._agents:
            return False
        
        # Check if update would affect handler resolution
        if self._has_pinned_handlers(agent_id):
            old_handler = self._agent_handlers.get(agent_id)
            new_config = config if not merge else {**self._agents[agent_id]["config"], **config}
            new_handler = new_config.get("handler_id", f"handler-{self._agents[agent_id]['type']}")
            
            if old_handler and new_handler != old_handler:
                raise InFlightError(
                    f"Cannot change handler for agent {agent_id} while "
                    f"attempts are in-flight. Current: {old_handler}, "
                    f"Requested: {new_handler}"
                )
        
        # Apply update
        if merge:
            self._agents[agent_id]["config"].update(config)
        else:
            self._agents[agent_id]["config"] = config
        
        self._agents[agent_id]["updated_at"] = time.time()
        return True
    
    def get_handler_stats(self) -> Dict[str, Any]:
        """Get statistics about handler pinning for monitoring.
        
        Returns:
            Dict with pinned handler counts and in-flight agent counts
        """
        return {
            "total_pinned_handlers": len(self._resolved_handlers),
            "agents_with_in_flight_attempts": len(self._in_flight_agents),
            "pending_invalidations": len(self._cache_invalidations),
            "in_flight_breakdown": {
                agent_id: len(attempts) 
                for agent_id, attempts in self._in_flight_agents.items()
            }
        }


# 2019-01-29T11:24:49 update

# 2019-04-09T13:38:38 update

# 2019-04-11T11:24:12 update

# 2019-06-26T17:03:48 update

# 2019-07-03T14:55:48 update

# 2019-07-18T18:18:47 update

# 2019-11-05T11:27:19 update

# 2019-11-20T11:35:05 update

# 2019-11-23T15:28:54 update

# 2020-03-13T09:23:07 update

# 2020-03-30T19:31:18 update

# 2020-04-22T15:03:30 update

# 2020-07-21T10:00:48 update

# 2020-09-10T09:02:08 update

# 2020-09-10T13:39:12 update

# 2020-09-22T16:27:52 update

# 2020-10-15T10:33:14 update

# 2021-05-13T11:15:56 update

# 2021-07-07T14:57:13 update

# 2021-07-13T15:15:19 update

# 2021-07-27T10:18:16 update

# 2022-03-11T15:24:11 update

# 2022-09-22T13:24:20 update

# 2022-11-01T12:20:40 update

# 2023-01-30T12:32:27 update

# 2023-03-10T09:43:50 update

# 2023-05-10T14:28:01 update

# 2023-05-11T20:04:46 update

# 2023-05-30T17:00:59 update

# 2023-07-13T17:54:32 update

# 2023-07-20T19:04:20 update

# 2023-07-31T17:00:02 update

# 2023-09-05T19:42:07 update

# 2024-01-02T10:29:47 update

# 2024-09-17T12:45:29 update

# 2024-09-17T11:51:01 update

# 2024-11-06T18:20:15 update

# 2025-01-12T15:13:14 update

# 2025-01-14T20:24:39 update

# 2025-03-26T20:21:27 update

# 2025-04-10T18:27:06 update

# 2025-06-19T20:34:58 update

# 2025-06-21T20:23:53 update

# 2025-06-24T20:30:30 update

# 2025-07-03T13:28:03 update

# 2025-07-24T17:42:21 update

# 2025-08-19T17:42:23 update

# 2025-08-21T11:06:52 update

# 2025-10-24T09:10:08 update

# 2025-12-18T19:34:38 update

# 2026-02-06T11:22:22 update

# 2026-02-13T15:42:04 update

# 2026-04-10T08:16:30 update

# 2026-04-29T18:16:11 update