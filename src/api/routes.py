"""API route definitions."""

import time
from fastapi import APIRouter, HTTPException, Depends
from typing import List, Dict, Optional

from src.agent import AgentRegistry, AgentStatus

router = APIRouter()
registry = AgentRegistry()


@router.get("/agents")
async def list_agents(status: Optional[str] = None, group: Optional[str] = None):
    status_filter = AgentStatus(status) if status else None
    return {"agents": registry.list(status=status_filter, group=group)}


@router.post("/agents")
async def register_agent(name: str, agent_type: str, config: Optional[Dict] = None):
    agent_id = registry.register(name, agent_type, config)
    return {"agent_id": agent_id, "status": "registered"}


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str):
    agent = registry.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str):
    if not registry.delete(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "deleted"}


@router.post("/agents/{agent_id}/start")
async def start_agent(agent_id: str):
    if not registry.update_status(agent_id, AgentStatus.RUNNING):
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "started"}


@router.post("/agents/{agent_id}/stop")
async def stop_agent(agent_id: str):
    if not registry.update_status(agent_id, AgentStatus.PAUSED):
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "stopped"}


@router.get("/agents/count")
async def agent_count():
    return {"count": registry.count()}


# Batch agent config update endpoint
import copy


@router.put("/agents/batch")
async def batch_update_agents(updates: List[Dict]):
    """Atomic batch update of agent configurations.

    If any update in the batch is invalid, the entire batch is rejected.
    This prevents partial success from masking failures (fixes #73).
    """
    if not updates:
        raise HTTPException(status_code=400, detail="Updates list cannot be empty")

    # Phase 1: Validate all updates before applying any
    validated = []
    for i, update in enumerate(updates):
        agent_id = update.get("agent_id")
        if not agent_id:
            raise HTTPException(
                status_code=400,
                detail=f"Update at index {i} missing 'agent_id'"
            )
        agent = registry.get(agent_id)
        if not agent:
            raise HTTPException(
                status_code=404,
                detail=f"Agent not found: {agent_id} (index {i})"
            )
        # Validate config fields if present
        config = update.get("config")
        if config is not None:
            if not isinstance(config, dict):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid config at index {i}: must be a dict"
                )
        validated.append((agent_id, update))

    # Phase 2: Apply all updates atomically
    # Snapshot original state for rollback on failure
    snapshots = {}
    for agent_id, update in validated:
        agent = registry.get(agent_id)
        snapshots[agent_id] = copy.deepcopy(agent)

    results = []
    try:
        for agent_id, update in validated:
            agent = registry.get(agent_id)
            if "config" in update:
                agent["config"].update(update["config"])
            if "name" in update:
                agent["name"] = update["name"]
            if "status" in update:
                try:
                    agent["status"] = AgentStatus(update["status"]).value
                except ValueError:
                    raise ValueError(f"Invalid status: {update['status']}")
            agent["updated_at"] = time.time()
            results.append({"agent_id": agent_id, "status": "updated"})
    except Exception as e:
        # Rollback all changes on any failure
        for agent_id, snapshot in snapshots.items():
            registry._agents[agent_id] = snapshot
        raise HTTPException(status_code=400, detail=f"Batch update failed, all changes rolled back: {e}")

    return {"updated": len(results), "results": results}
