"""Tests for CORS middleware OPTIONS handling."""
import pytest
from starlette.testclient import TestClient
from src.api.middleware import CORSMiddleware, AuthMiddleware
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.responses import JSONResponse


async def health(request):
    return JSONResponse({"status": "ok"})


app = Starlette(routes=[Route("/api/v2/health", health)])
app.add_middleware(CORSMiddleware)
app.add_middleware(AuthMiddleware)

client = TestClient(app)


def test_options_preflight_returns_200():
    """Test that OPTIONS preflight returns 200 with CORS headers."""
    response = client.options(
        "/api/v2/health",
        headers={
            "origin": "https://example.com",
            "access-control-request-method": "POST",
        }
    )
    assert response.status_code == 200
    assert "Access-Control-Allow-Origin" in response.headers
    assert "Access-Control-Allow-Methods" in response.headers


def test_real_request_requires_auth():
    """Test that non-OPTIONS requests still require auth."""
    response = client.get("/api/v2/health")
    assert response.status_code == 401


def test_real_request_with_auth():
    """Test that authenticated requests work."""
    response = client.get(
        "/api/v2/health",
        headers={"Authorization": "Bearer test-token"}
    )
    assert response.status_code == 200
