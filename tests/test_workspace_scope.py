"""Tests for workspace-scoped API endpoints and registry operations."""

import pytest
from fastapi.testclient import TestClient

from src.api.server import create_app
from src.agent.registry import AgentRegistry


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


@pytest.fixture
def auth_headers_ws1():
    return {
        "Authorization": "Bearer test-token",
        "X-Workspace-Id": "ws-001",
        "X-Workspace-Role": "admin",
        "X-User-Id": "user-1",
    }


@pytest.fixture
def auth_headers_ws2():
    return {
        "Authorization": "Bearer test-token",
        "X-Workspace-Id": "ws-002",
        "X-Workspace-Role": "member",
        "X-User-Id": "user-2",
    }


@pytest.fixture
def auth_headers_viewer():
    return {
        "Authorization": "Bearer test-token",
        "X-Workspace-Id": "ws-001",
        "X-Workspace-Role": "viewer",
        "X-User-Id": "user-3",
    }


class TestWorkspaceContextEnforcement:
    """Verify that all endpoints reject requests without workspace context."""

    def test_list_agents_requires_workspace(self, client):
        resp = client.get("/api/v2/agents")
        assert resp.status_code == 401

    def test_register_agent_requires_workspace(self, client):
        resp = client.post("/api/v2/agents", params={"name": "a", "agent_type": "test"})
        assert resp.status_code == 401

    def test_get_agent_requires_workspace(self, client):
        resp = client.get("/api/v2/agents/some-id")
        assert resp.status_code == 401

    def test_delete_agent_requires_workspace(self, client):
        resp = client.delete("/api/v2/agents/some-id")
        assert resp.status_code == 401

    def test_search_runs_requires_workspace(self, client):
        resp = client.get("/api/v2/runs/search")
        assert resp.status_code == 401

    def test_invalid_workspace_role_rejected(self, client):
        headers = {
            "Authorization": "Bearer test-token",
            "X-Workspace-Id": "ws-001",
            "X-Workspace-Role": "superadmin",
        }
        resp = client.get("/api/v2/agents", headers=headers)
        assert resp.status_code == 401


class TestWorkspaceIsolation:
    """Verify that workspace A cannot access workspace B's resources."""

    def test_register_and_list_scoped_to_workspace(self, client, auth_headers_ws1, auth_headers_ws2):
        # Register agent in ws-001
        resp = client.post(
            "/api/v2/agents",
            params={"name": "ws1-agent", "agent_type": "test.type"},
            headers=auth_headers_ws1,
        )
        assert resp.status_code == 200
        agent_id = resp.json()["agent_id"]

        # ws-001 can see its agent
        resp = client.get("/api/v2/agents", headers=auth_headers_ws1)
        assert resp.status_code == 200
        assert len(resp.json()["agents"]) == 1

        # ws-002 sees empty list
        resp = client.get("/api/v2/agents", headers=auth_headers_ws2)
        assert resp.status_code == 200
        assert len(resp.json()["agents"]) == 0

    def test_get_agent_returns_403_for_wrong_workspace(self, client, auth_headers_ws1, auth_headers_ws2):
        # Register in ws-001
        resp = client.post(
            "/api/v2/agents",
            params={"name": "ws1-agent", "agent_type": "test.type"},
            headers=auth_headers_ws1,
        )
        agent_id = resp.json()["agent_id"]

        # ws-002 cannot access ws-001's agent — gets 403
        resp = client.get(f"/api/v2/agents/{agent_id}", headers=auth_headers_ws2)
        assert resp.status_code == 403

    def test_delete_agent_returns_403_for_wrong_workspace(self, client, auth_headers_ws1, auth_headers_ws2):
        resp = client.post(
            "/api/v2/agents",
            params={"name": "ws1-agent", "agent_type": "test.type"},
            headers=auth_headers_ws1,
        )
        agent_id = resp.json()["agent_id"]

        # ws-002 cannot delete ws-001's agent
        resp = client.delete(f"/api/v2/agents/{agent_id}", headers=auth_headers_ws2)
        assert resp.status_code == 403

    def test_start_agent_returns_403_for_wrong_workspace(self, client, auth_headers_ws1, auth_headers_ws2):
        resp = client.post(
            "/api/v2/agents",
            params={"name": "ws1-agent", "agent_type": "test.type"},
            headers=auth_headers_ws1,
        )
        agent_id = resp.json()["agent_id"]

        resp = client.post(f"/api/v2/agents/{agent_id}/start", headers=auth_headers_ws2)
        assert resp.status_code == 403

    def test_agent_count_scoped_to_workspace(self, client, auth_headers_ws1, auth_headers_ws2):
        # Register 2 agents in ws-001
        client.post("/api/v2/agents", params={"name": "a1", "agent_type": "t1"}, headers=auth_headers_ws1)
        client.post("/api/v2/agents", params={"name": "a2", "agent_type": "t2"}, headers=auth_headers_ws1)

        # Register 1 agent in ws-002
        client.post("/api/v2/agents", params={"name": "b1", "agent_type": "t1"}, headers=auth_headers_ws2)

        resp = client.get("/api/v2/agents/count", headers=auth_headers_ws1)
        assert resp.json()["count"] == 2

        resp = client.get("/api/v2/agents/count", headers=auth_headers_ws2)
        assert resp.json()["count"] == 1


class TestRunSearchScoping:
    """Verify run search is scoped to workspace."""

    def test_search_returns_only_workspace_agents(self, client, auth_headers_ws1, auth_headers_ws2):
        # Register in ws-001
        client.post("/api/v2/agents", params={"name": "prod-agent", "agent_type": "prod.checker"}, headers=auth_headers_ws1)
        # Register in ws-002
        client.post("/api/v2/agents", params={"name": "dev-agent", "agent_type": "dev.runner"}, headers=auth_headers_ws2)

        # ws-001 search only sees its agents
        resp = client.get("/api/v2/runs/search", headers=auth_headers_ws1)
        assert resp.status_code == 200
        data = resp.json()
        assert data["workspace_id"] == "ws-001"
        assert len(data["runs"]) == 1
        assert data["runs"][0]["name"] == "prod-agent"

        # ws-002 search only sees its agents
        resp = client.get("/api/v2/runs/search", headers=auth_headers_ws2)
        assert resp.status_code == 200
        data = resp.json()
        assert data["workspace_id"] == "ws-002"
        assert len(data["runs"]) == 1
        assert data["runs"][0]["name"] == "dev-agent"

    def test_search_with_query_filter(self, client, auth_headers_ws1):
        client.post("/api/v2/agents", params={"name": "prod-agent", "agent_type": "prod.checker"}, headers=auth_headers_ws1)
        client.post("/api/v2/agents", params={"name": "dev-agent", "agent_type": "dev.runner"}, headers=auth_headers_ws1)

        resp = client.get("/api/v2/runs/search", params={"query": "prod"}, headers=auth_headers_ws1)
        assert resp.status_code == 200
        assert len(resp.json()["runs"]) == 1
        assert resp.json()["runs"][0]["name"] == "prod-agent"

    def test_search_with_status_filter(self, client, auth_headers_ws1):
        resp = client.post("/api/v2/agents", params={"name": "agent1", "agent_type": "test"}, headers=auth_headers_ws1)
        agent_id = resp.json()["agent_id"]
        # Start it
        client.post(f"/api/v2/agents/{agent_id}/start", headers=auth_headers_ws1)

        resp = client.get("/api/v2/runs/search", params={"status": "running"}, headers=auth_headers_ws1)
        assert resp.status_code == 200
        assert len(resp.json()["runs"]) == 1


class TestRoleBasedAccess:
    """Verify role-based access controls on workspace-scoped endpoints."""

    def test_viewer_cannot_register_agent(self, client, auth_headers_viewer):
        resp = client.post(
            "/api/v2/agents",
            params={"name": "new-agent", "agent_type": "test"},
            headers=auth_headers_viewer,
        )
        assert resp.status_code == 403

    def test_viewer_cannot_delete_agent(self, client, auth_headers_ws1, auth_headers_viewer):
        # Admin registers
        resp = client.post(
            "/api/v2/agents",
            params={"name": "test-agent", "agent_type": "test"},
            headers=auth_headers_ws1,
        )
        agent_id = resp.json()["agent_id"]

        # Viewer cannot delete
        viewer_headers = auth_headers_viewer
        resp = client.delete(f"/api/v2/agents/{agent_id}", headers=viewer_headers)
        assert resp.status_code == 403

    def test_viewer_can_list_and_search(self, client, auth_headers_ws1, auth_headers_viewer):
        # Register with admin
        client.post("/api/v2/agents", params={"name": "test-agent", "agent_type": "test"}, headers=auth_headers_ws1)

        # Viewer can list
        resp = client.get("/api/v2/agents", headers=auth_headers_viewer)
        assert resp.status_code == 200

        # Viewer can search
        resp = client.get("/api/v2/runs/search", headers=auth_headers_viewer)
        assert resp.status_code == 200


class TestRegistryWorkspaceScoping:
    """Unit tests for registry workspace-scoped methods."""

    def test_get_with_workspace_match(self):
        reg = AgentRegistry()
        aid = reg.register("test", "t1", workspace_id="ws-1")
        assert reg.get(aid, workspace_id="ws-1") is not None

    def test_get_with_workspace_mismatch_returns_none(self):
        reg = AgentRegistry()
        aid = reg.register("test", "t1", workspace_id="ws-1")
        assert reg.get(aid, workspace_id="ws-2") is None

    def test_delete_with_workspace_mismatch_fails(self):
        reg = AgentRegistry()
        aid = reg.register("test", "t1", workspace_id="ws-1")
        assert reg.delete(aid, workspace_id="ws-2") is False
        # Agent still exists
        assert reg.get(aid, workspace_id="ws-1") is not None

    def test_update_status_with_workspace_mismatch_fails(self):
        reg = AgentRegistry()
        aid = reg.register("test", "t1", workspace_id="ws-1")
        assert reg.update_status(aid, AgentStatus.RUNNING, workspace_id="ws-2") is False

    def test_search_runs_isolated_to_workspace(self):
        reg = AgentRegistry()
        reg.register("alpha", "type.a", workspace_id="ws-1")
        reg.register("beta", "type.b", workspace_id="ws-2")

        results = reg.search_runs(workspace_id="ws-1")
        assert len(results) == 1
        assert results[0]["name"] == "alpha"

        results = reg.search_runs(workspace_id="ws-2")
        assert len(results) == 1
        assert results[0]["name"] == "beta"

    def test_search_runs_with_no_workspace_raises(self):
        """search_runs requires workspace_id — empty workspace returns empty list."""
        reg = AgentRegistry()
        reg.register("alpha", "type.a", workspace_id="ws-1")
        # Searching a workspace with no agents
        results = reg.search_runs(workspace_id="ws-999")
        assert results == []

    def test_count_scoped_to_workspace(self):
        reg = AgentRegistry()
        reg.register("a", "t1", workspace_id="ws-1")
        reg.register("b", "t2", workspace_id="ws-1")
        reg.register("c", "t3", workspace_id="ws-2")

        assert reg.count(workspace_id="ws-1") == 2
        assert reg.count(workspace_id="ws-2") == 1
        assert reg.count() == 3
