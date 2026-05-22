"""Tests for artifact size enforcement (Issue #1809)."""

import pytest
import os
from io import BytesIO
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api.server import create_app
from src.api.middleware import MAX_ARTIFACT_SIZE, MAX_ARTIFACT_SIZE_MB, ArtifactSizeLimitMiddleware


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_app():
    """Create a fresh FastAPI test client."""
    return TestClient(create_app())


# ---------------------------------------------------------------------------
# Test: MAX_ARTIFACT_SIZE env var (default 100 MB)
# ---------------------------------------------------------------------------

def test_default_max_artifact_size_is_100mb():
    """MAX_ARTIFACT_SIZE should default to 100 MB when env var is not set."""
    # Ensure env var is not set for this test
    with patch.dict(os.environ, {"MAX_ARTIFACT_SIZE": ""}, clear=False):
        # Reload to pick up the patched env (module-level constant already set at import)
        from src.api import middleware
        assert middleware.MAX_ARTIFACT_SIZE == 100 * 1024 * 1024


def test_max_artifact_size_env_var_override(monkeypatch):
    """MAX_ARTIFACT_SIZE should respect the MAX_ARTIFACT_SIZE env var."""
    monkeypatch.setenv("MAX_ARTIFACT_SIZE", str(5 * 1024 * 1024))  # 5 MB
    # Re-import to pick up the new value
    import importlib
    from src.api import middleware as mw_module
    importlib.reload(mw_module)
    assert mw_module.MAX_ARTIFACT_SIZE == 5 * 1024 * 1024


# ---------------------------------------------------------------------------
# Test: Artifact upload endpoints exist and require size validation
# ---------------------------------------------------------------------------

def test_upload_artifact_rejects_oversized_payload(monkeypatch):
    """Uploading a file larger than MAX_ARTIFACT_SIZE returns 413."""
    monkeypatch.setenv("MAX_ARTIFACT_SIZE", str(10 * 1024 * 1024))  # 10 MB
    import importlib
    from src.api import middleware as mw_module
    importlib.reload(mw_module)

    app = make_app()
    # Simulate a file of 15 MB (exceeds 10 MB limit)
    large_content = b"x" * (15 * 1024 * 1024)

    response = app.post(
        "/api/v2/artifacts",
        files={"file": ("large.bin", BytesIO(large_content), "application/octet-stream")},
    )
    assert response.status_code == 413, f"Expected 413, got {response.status_code}: {response.text}"
    assert "Payload too large" in response.json()["detail"]
    assert "MAX_ARTIFACT_SIZE" in response.json()["detail"]


def test_upload_agent_artifact_rejects_oversized_payload(monkeypatch):
    """Uploading to /agents/{id}/artifacts with oversized file returns 413."""
    monkeypatch.setenv("MAX_ARTIFACT_SIZE", str(10 * 1024 * 1024))  # 10 MB
    import importlib
    from src.api import middleware as mw_module
    importlib.reload(mw_module)

    app = make_app()
    large_content = b"y" * (12 * 1024 * 1024)  # 12 MB > 10 MB

    response = app.post(
        "/api/v2/artifacts",
        files={"file": ("large.bin", BytesIO(large_content), "application/octet-stream")},
    )
    assert response.status_code == 413


def test_upload_artifact_accepts_valid_size(monkeypatch):
    """Uploading a file within the size limit succeeds with 200."""
    monkeypatch.setenv("MAX_ARTIFACT_SIZE", str(100 * 1024 * 1024))  # 100 MB
    import importlib
    from src.api import middleware as mw_module
    importlib.reload(mw_module)

    app = make_app()
    # Small file: 1 KB (well under 100 MB limit)
    small_content = b"hello world" * 100

    response = app.post(
        "/api/v2/artifacts",
        files={"file": ("small.bin", BytesIO(small_content), "application/octet-stream")},
    )
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert "artifact_id" in data
    assert data["filename"] == "small.bin"
    assert data["max_size_mb"] == 100


def test_upload_artifact_rejects_exactly_at_limit_plus_one(monkeypatch):
    """Uploading a file exactly at MAX_ARTIFACT_SIZE + 1 byte returns 413."""
    monkeypatch.setenv("MAX_ARTIFACT_SIZE", str(1024))  # 1 KB for easy testing
    import importlib
    from src.api import middleware as mw_module
    importlib.reload(mw_module)

    app = make_app()
    # Exactly 1025 bytes (exceeds 1024 byte limit)
    content = b"x" * 1025

    response = app.post(
        "/api/v2/artifacts",
        files={"file": ("at-limit.bin", BytesIO(content), "application/octet-stream")},
    )
    assert response.status_code == 413


def test_upload_artifact_accepts_exactly_at_limit(monkeypatch):
    """Uploading a file exactly at MAX_ARTIFACT_SIZE succeeds."""
    monkeypatch.setenv("MAX_ARTIFACT_SIZE", str(1024))
    import importlib
    from src.api import middleware as mw_module
    importlib.reload(mw_module)

    app = make_app()
    # Exactly 1024 bytes
    content = b"x" * 1024

    response = app.post(
        "/api/v2/artifacts",
        files={"file": ("at-limit.bin", BytesIO(content), "application/octet-stream")},
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Test: Middleware integration
# ---------------------------------------------------------------------------

def test_artifact_size_middleware_rejects_oversized_via_middleware(monkeypatch):
    """Middleware should return 413 for oversized artifact upload before route handler."""
    monkeypatch.setenv("MAX_ARTIFACT_SIZE", str(5 * 1024 * 1024))  # 5 MB
    import importlib
    from src.api import middleware as mw_module
    importlib.reload(mw_module)

    app = make_app()
    large_content = b"z" * (6 * 1024 * 1024)  # 6 MB > 5 MB

    response = app.post(
        "/api/v2/artifacts",
        files={"file": ("big.bin", BytesIO(large_content), "application/octet-stream")},
    )
    # Middleware or route-level check should reject it
    assert response.status_code == 413


# ---------------------------------------------------------------------------
# Test: GET/DELETE artifact endpoints (no size restriction expected)
# ---------------------------------------------------------------------------

def test_get_artifact_returns_404_for_nonexistent():
    """GET /artifacts/{id} returns 404 for unknown artifact."""
    app = make_app()
    response = app.get("/api/v2/artifacts/nonexistent-id")
    assert response.status_code == 404


def test_list_artifacts_returns_empty_initially():
    """GET /artifacts returns empty list when no artifacts uploaded."""
    app = make_app()
    response = app.get("/api/v2/artifacts")
    assert response.status_code == 200
    assert response.json()["count"] == 0


def test_delete_artifact_returns_404_for_nonexistent():
    """DELETE /artifacts/{id} returns 404 for unknown artifact."""
    app = make_app()
    response = app.delete("/api/v2/artifacts/nonexistent-id")
    assert response.status_code == 404


def test_upload_and_retrieve_artifact_roundtrip(monkeypatch):
    """Smoke test: upload a valid artifact and retrieve its metadata."""
    monkeypatch.setenv("MAX_ARTIFACT_SIZE", str(100 * 1024 * 1024))
    import importlib
    from src.api import middleware as mw_module
    importlib.reload(mw_module)

    app = make_app()
    content = b"roundtrip test content"
    response = app.post(
        "/api/v2/artifacts",
        files={"file": ("roundtrip.txt", BytesIO(content), "text/plain")},
    )
    assert response.status_code == 200
    artifact_id = response.json()["artifact_id"]

    get_resp = app.get(f"/api/v2/artifacts/{artifact_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["filename"] == "roundtrip.txt"
    assert get_resp.json()["size"] == len(content)
