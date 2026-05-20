"""Tests for ingress middleware and rate limiting before body parsing."""
import pytest
import time
from unittest.mock import MagicMock
from src.api.middleware import IngressMiddleware, RateLimitMiddleware
from starlette.requests import Request
from starlette.responses import Response


def make_mock_request(host="127.0.0.1", content_length=None, content_type=None, headers=None):
    """Create a mock Request with optional headers."""
    h = dict(headers or {})
    if content_length is not None:
        h["content-length"] = str(content_length)
    if content_type:
        h["content-type"] = content_type

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v2/data",
        "headers": [(k.encode(), v.encode()) for k, v in h.items()],
        "client": (host, 12345),
    }
    return Request(scope)


async def test_ingress_rejects_large_body():
    """Test that IngressMiddleware rejects oversized bodies before parsing."""
    app = MagicMock()
    middleware = IngressMiddleware(app, max_body_size=1024)

    # Create a request with Content-Length > max_body_size
    request = make_mock_request(content_length=10000)

    async def call_next(req):
        return Response(status_code=200)

    response = await middleware.dispatch(request, call_next)

    assert response.status_code == 413
    assert "body too large" in response.body.decode().lower()


async def test_ingress_accepts_small_body():
    """Test that IngressMiddleware allows small bodies."""
    app = MagicMock()
    middleware = IngressMiddleware(app, max_body_size=1024)

    request = make_mock_request(content_length=100)

    async def call_next(req):
        return Response(status_code=200)

    response = await middleware.dispatch(request, call_next)
    assert response.status_code == 200


async def test_rate_limit_rejects_over_limit():
    """Test that rate limit blocks requests BEFORE body parsing."""
    app = MagicMock()
    middleware = RateLimitMiddleware(app, max_requests=2, window=60)

    async def call_next(req):
        # This should NOT be called if rate limited
        raise AssertionError("call_next should not be reached after rate limit")

    request1 = make_mock_request(host="10.0.0.1")
    request2 = make_mock_request(host="10.0.0.1")
    request3 = make_mock_request(host="10.0.0.1")  # Should be rejected

    r1 = await middleware.dispatch(request1, call_next)
    assert r1.status_code == 200

    r2 = await middleware.dispatch(request2, call_next)
    assert r2.status_code == 200

    # Third request should be 429 without calling call_next
    r3 = await middleware.dispatch(request3, call_next)
    assert r3.status_code == 429
    assert "Retry-After" in dict(r3.headers)


async def test_rate_limit_allows_after_window():
    """Test that rate limit resets after window expires."""
    app = MagicMock()
    # Very short window for testing
    middleware = RateLimitMiddleware(app, max_requests=1, window=1)

    async def call_next(req):
        return Response(status_code=200)

    r1 = await middleware.dispatch(make_mock_request(host="10.0.0.2"), call_next)
    assert r1.status_code == 200

    r2 = await middleware.dispatch(make_mock_request(host="10.0.0.2"), call_next)
    assert r2.status_code == 429

    # Wait for window to expire
    time.sleep(1.1)

    r3 = await middleware.dispatch(make_mock_request(host="10.0.0.2"), call_next)
    assert r3.status_code == 200


async def test_rate_limit_per_client():
    """Test that rate limits are tracked per client, not globally."""
    app = MagicMock()
    middleware = RateLimitMiddleware(app, max_requests=1, window=60)

    async def call_next(req):
        return Response(status_code=200)

    r1 = await middleware.dispatch(make_mock_request(host="10.0.0.3"), call_next)
    assert r1.status_code == 200

    r2 = await middleware.dispatch(make_mock_request(host="10.0.0.3"), call_next)
    assert r2.status_code == 429

    # Different client should still be allowed
    r3 = await middleware.dispatch(make_mock_request(host="10.0.0.4"), call_next)
    assert r3.status_code == 200


async def test_x_forwarded_for_header():
    """Test that X-Forwarded-For header is used for rate limiting."""
    app = MagicMock()
    middleware = RateLimitMiddleware(app, max_requests=1, window=60)

    async def call_next(req):
        return Response(status_code=200)

    req1 = make_mock_request(host="10.0.0.5", headers={"X-Forwarded-For": "1.2.3.4, 5.6.7.8"})
    req2 = make_mock_request(host="10.0.0.5", headers={"X-Forwarded-For": "1.2.3.4, 5.6.7.8"})
    req3 = make_mock_request(host="10.0.0.5", headers={"X-Forwarded-For": "9.9.9.9"})  # Different IP

    r1 = await middleware.dispatch(req1, call_next)
    assert r1.status_code == 200

    r2 = await middleware.dispatch(req2, call_next)
    assert r2.status_code == 429

    # Different forwarded IP should be allowed
    r3 = await middleware.dispatch(req3, call_next)
    assert r3.status_code == 200
