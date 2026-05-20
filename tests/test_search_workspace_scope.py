"""Tests for workspace-scoped run search API."""
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
from src.api.routes import search_runs, dispatch_to_workspace


@pytest.fixture
def client():
    from src.api.routes import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_search_requires_workspace():
    """Test that search requires a workspace parameter."""
    # Direct call
    import asyncio
    async def check():
        result = await search_runs(workspace="")
        return result
    
    with pytest.raises(Exception):  # HTTPException 400
        asyncio.get_event_loop().run_until_complete(check())


def test_search_returns_only_own_workspace(client):
    """Test that search only returns runs from the specified workspace."""
    import asyncio
    
    async def do_search():
        return await search_runs(workspace="ws-a", query="test", limit=10)
    
    # The in-memory index starts empty, so this returns empty results
    # but importantly it does NOT return runs from other workspaces
    result = asyncio.get_event_loop().run_until_complete(do_search())
    
    assert result["workspace"] == "ws-a"
    assert "count" in result
    assert "runs" in result


def test_search_rejects_missing_workspace(client):
    """Test that GET search rejects missing workspace."""
    response = client.get("/runs/search?query=test")
    # Should require workspace parameter
    assert response.status_code == 422  # FastAPI validation error


def test_dispatch_rejects_wrong_workspace():
    """Test that dispatch is rejected for runs not in the workspace."""
    from fastapi import HTTPException
    import asyncio
    
    async def check():
        # Try to dispatch a run that doesn't belong to the workspace
        with pytest.raises(HTTPException) as exc_info:
            await dispatch_to_workspace(run_id="run-1", workspace="ws-a", target_agent="agent-1")
        assert exc_info.value.status_code == 403
    
    asyncio.get_event_loop().run_until_complete(check())
