"""API route definitions — all endpoints scoped to authenticated workspace."""

from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Dict, Optional

from src.agent import AgentRegistry, AgentStatus
from src.api.middleware import WorkspaceContext, get_workspace_context, require_workspace_role

router = APIRouter()
registry = AgentRegistry()


def _validate_workspace_access(agent_id: str, ctx: WorkspaceContext) -> Dict:
    """
    Fetch agent and validate it belongs to the caller's workspace.
    
    Raises:
        HTTPException 404 if agent not found in workspace scope
        HTTPException 403 if agent exists but belongs to different workspace
    """
    agent = registry.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.get("workspace_id") != ctx.workspace_id:
        raise HTTPException(
            status_code=403,
            detail=f"Agent '{agent_id}' not accessible in workspace '{ctx.workspace_id}'"
        )
    return agent


@router.get("/agents")
async def list_agents(
    status: Optional[str] = None,
    group: Optional[str] = None,
    ctx: WorkspaceContext = Depends(get_workspace_context),
):
    """List agents scoped to the authenticated workspace."""
    status_filter = AgentStatus(status) if status else None
    return {"agents": registry.list(status=status_filter, group=group, workspace_id=ctx.workspace_id)}


@router.post("/agents")
async def register_agent(
    name: str,
    agent_type: str,
    config: Optional[Dict] = None,
    ctx: WorkspaceContext = Depends(require_workspace_role("member")),
):
    """Register a new agent in the authenticated workspace."""
    agent_id = registry.register(name, agent_type, config, workspace_id=ctx.workspace_id)
    return {"agent_id": agent_id, "workspace_id": ctx.workspace_id, "status": "registered"}


@router.get("/agents/{agent_id}")
async def get_agent(
    agent_id: str,
    ctx: WorkspaceContext = Depends(get_workspace_context),
):
    """Get agent details — validates workspace scope before returning."""
    return _validate_workspace_access(agent_id, ctx)


@router.delete("/agents/{agent_id}")
async def delete_agent(
    agent_id: str,
    ctx: WorkspaceContext = Depends(require_workspace_role("admin")),
):
    """Delete agent — validates workspace scope, requires admin role."""
    _validate_workspace_access(agent_id, ctx)
    if not registry.delete(agent_id, workspace_id=ctx.workspace_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "deleted"}


@router.post("/agents/{agent_id}/start")
async def start_agent(
    agent_id: str,
    ctx: WorkspaceContext = Depends(require_workspace_role("member")),
):
    """Start agent — validates workspace scope."""
    _validate_workspace_access(agent_id, ctx)
    if not registry.update_status(agent_id, AgentStatus.RUNNING, workspace_id=ctx.workspace_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "started"}


@router.post("/agents/{agent_id}/stop")
async def stop_agent(
    agent_id: str,
    ctx: WorkspaceContext = Depends(require_workspace_role("member")),
):
    """Stop agent — validates workspace scope."""
    _validate_workspace_access(agent_id, ctx)
    if not registry.update_status(agent_id, AgentStatus.PAUSED, workspace_id=ctx.workspace_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "stopped"}


@router.get("/agents/count")
async def agent_count(
    ctx: WorkspaceContext = Depends(get_workspace_context),
):
    """Count agents scoped to the authenticated workspace."""
    return {"count": registry.count(workspace_id=ctx.workspace_id)}


@router.get("/runs/search")
async def search_runs(
    query: Optional[str] = Query(None, description="Text search on agent name/type"),
    status: Optional[str] = Query(None, description="Filter by agent status"),
    limit: int = Query(50, ge=1, le=200, description="Maximum results"),
    ctx: WorkspaceContext = Depends(get_workspace_context),
):
    """
    Search for runs within the authenticated workspace.
    
    All queries are scoped to the caller's workspace_id.
    Cross-workspace data leakage is prevented by:
    1. Requiring WorkspaceContext via dependency injection
    2. Passing workspace_id to the registry search method
    3. The registry only indexes and returns agents belonging to the workspace
    """
    results = registry.search_runs(
        workspace_id=ctx.workspace_id,
        query=query,
        status=status,
        limit=limit,
    )
    return {"runs": results, "workspace_id": ctx.workspace_id, "count": len(results)}
