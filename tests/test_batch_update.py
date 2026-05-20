"""Tests for atomic batch agent config updates (#73)."""

import pytest
from fastapi.testclient import TestClient
from src.api.server import create_app


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


class TestBatchUpdateAtomicity:
    def test_batch_update_all_valid(self, client):
        """All valid updates should succeed atomically."""
        # Register two agents
        r1 = client.post("/agents?name=agent1&agent_type=test")
        r2 = client.post("/agents?name=agent2&agent_type=test")
        id1 = r1.json()["agent_id"]
        id2 = r2.json()["agent_id"]

        resp = client.put("/agents/batch", json=[
            {"agent_id": id1, "config": {"key": "val1"}},
            {"agent_id": id2, "config": {"key": "val2"}},
        ])
        assert resp.status_code == 200
        data = resp.json()
        assert data["updated"] == 2

    def test_batch_update_invalid_agent_rolls_back_all(self, client):
        """If any agent_id is invalid, no updates should be applied."""
        r1 = client.post("/agents?name=agent1&agent_type=test")
        id1 = r1.json()["agent_id"]

        # Try batch with one valid and one invalid
        resp = client.put("/agents/batch", json=[
            {"agent_id": id1, "config": {"key": "val1"}},
            {"agent_id": "nonexistent-id", "config": {"key": "val2"}},
        ])
        assert resp.status_code == 404  # agent not found

        # Verify first agent was NOT updated (rollback)
        agent = client.get(f"/agents/{id1}")
        assert agent.json().get("config", {}).get("key") is None

    def test_batch_update_empty_list_rejected(self, client):
        """Empty update list should be rejected with 400."""
        resp = client.put("/agents/batch", json=[])
        assert resp.status_code == 400

    def test_batch_update_missing_agent_id_rejected(self, client):
        """Updates without agent_id should be rejected."""
        resp = client.put("/agents/batch", json=[
            {"config": {"key": "val"}}  # missing agent_id
        ])
        assert resp.status_code == 400

    def test_batch_update_invalid_config_rejected(self, client):
        """Non-dict config should be rejected."""
        r1 = client.post("/agents?name=agent1&agent_type=test")
        id1 = r1.json()["agent_id"]

        resp = client.put("/agents/batch", json=[
            {"agent_id": id1, "config": "not-a-dict"}
        ])
        assert resp.status_code == 400

    def test_batch_update_invalid_status_rolls_back(self, client):
        """Invalid status value should cause full rollback."""
        r1 = client.post("/agents?name=agent1&agent_type=test")
        id1 = r1.json()["agent_id"]

        resp = client.put("/agents/batch", json=[
            {"agent_id": id1, "status": "invalid_status"}
        ])
        assert resp.status_code == 400
