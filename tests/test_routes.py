from fastapi.testclient import TestClient
from src.main import app

client = TestClient(app)

def test_unauthorized_access():
    """Test all endpoints require authentication."""
    # Test list agents without token
    response = client.get("/agents")
    assert response.status_code == 401
    # Test register agent without token
    response = client.post("/agents", params={"name": "test", "agent_type": "test.type"})
    assert response.status_code == 401
    # Test batch update without token
    response = client.post("/agents/batch-update", json=[{"agent_id": "test"}])
    assert response.status_code == 401

def test_batch_update_invalid_token():
    """Test access with invalid token returns 401."""
    headers = {"Authorization": "Bearer invalid_token"}
    response = client.get("/agents", headers=headers)
    assert response.status_code == 401
    assert "Invalid authentication credentials" in response.json()["detail"]

def test_register_and_batch_update_valid():
    """Test valid batch update with valid token."""
    headers = {"Authorization": "Bearer valid_token"}
    # Register an agent
    response = client.post("/agents", params={"name": "test_agent", "agent_type": "test.type"}, headers=headers)
    assert response.status_code == 200
    agent_id = response.json()["agent_id"]
    # Batch update the agent
    response = client.post("/agents/batch-update", json=[{"agent_id": agent_id, "status": "running"}], headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert agent_id in response.json()["updated"]
    # Verify the agent status was updated
    response = client.get(f"/agents/{agent_id}", headers=headers)
    assert response.json()["status"] == "running"

def test_batch_update_invalid_agent_id():
    """Test batch update with invalid agent_id returns 400."""
    headers = {"Authorization": "Bearer valid_token"}
    response = client.post("/agents/batch-update", json=[{"agent_id": "invalid_id", "status": "running"}], headers=headers)
    assert response.status_code == 400
    assert any("Agent invalid_id not found" in error["message"] for error in response.json()["detail"])

def test_batch_update_invalid_status():
    """Test batch update with invalid status returns 400."""
    headers = {"Authorization": "Bearer valid_token"}
    # Register an agent
    response = client.post("/agents", params={"name": "test_agent2", "agent_type": "test.type"}, headers=headers)
    assert response.status_code == 200
    agent_id = response.json()["agent_id"]
    # Batch update with invalid status
    response = client.post("/agents/batch-update", json=[{"agent_id": agent_id, "status": "invalid_status"}], headers=headers)
    assert response.status_code == 400
    assert any("Invalid status: invalid_status" in error["message"] for error in response.json()["detail"])

def test_batch_update_partial_failure():
    """Test that partial failure prevents any mutation."""
    headers = {"Authorization": "Bearer valid_token"}
    # Register a valid agent
    response = client.post("/agents", params={"name": "test_agent3", "agent_type": "test.type"}, headers=headers)
    assert response.status_code == 200
    valid_agent_id = response.json()["agent_id"]
    # Get original status
    original_status = client.get(f"/agents/{valid_agent_id}", headers=headers).json()["status"]
    # Send batch with one valid and one invalid agent_id
    response = client.post("/agents/batch-update", json=[
        {"agent_id": valid_agent_id, "status": "running"},
        {"agent_id": "invalid_id", "status": "running"}
    ], headers=headers)
    assert response.status_code == 400
    # Verify the valid agent's status was not updated
    response = client.get(f"/agents/{valid_agent_id}", headers=headers)
    assert response.json()["status"] == original_status  # Should still be pending
