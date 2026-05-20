"""API middleware components."""

import time
import logging
from typing import Callable
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path.startswith("/api/v2") and request.url.path != "/api/v2/auth/token":
            token = request.headers.get("Authorization", "")
            if not token.startswith("Bearer "):
                return Response(status_code=401, content="Unauthorized")
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_requests: int = 100, window: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window = window
        self._requests = {}

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()

        if client_ip not in self._requests:
            self._requests[client_ip] = []

        self._requests[client_ip] = [t for t in self._requests[client_ip] if now - t < self.window]

        if len(self._requests[client_ip]) >= self.max_requests:
            return Response(status_code=429, content="Too many requests")

        self._requests[client_ip].append(now)
        return await call_next(request)


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = time.time()
        response = await call_next(request)
        duration = time.time() - start
        logger.info(f"{request.method} {request.url.path} {response.status_code} {duration:.3f}s")
        return response


class RBACMiddleware(BaseHTTPMiddleware):
    """Enforce role-based access control on protected routes."""

    def __init__(self, app, auth_guard=None):
        super().__init__(app)
        self.auth_guard = auth_guard or AuthGuard()

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Only check RBAC for run cancellation endpoints
        if request.method == "POST" and "/cancel" in request.url.path:
            session_id = request.headers.get("X-Session-Id", "")
            workspace_id = request.headers.get("X-Workspace-Id", "")
            if not self.auth_guard.can_cancel_run(session_id, workspace_id):
                return Response(status_code=403, content="Forbidden: insufficient permissions for run cancellation")
        return await call_next(request)


from src.auth import AuthGuard
