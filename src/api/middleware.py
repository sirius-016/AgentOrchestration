"""API middleware components."""

import time
import logging
import json
from typing import Callable, Dict, Any, List
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse

logger = logging.getLogger(__name__)

# Sensitive fields that should be filtered before serialization
SENSITIVE_FIELDS = {'password', 'token', 'secret', 'key', 'authorization', 'cookie', 'session'}


def sanitize_exception(exception_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Remove sensitive fields from exception dict before JSON serialization.
    
    Args:
        exception_dict: Dictionary containing exception details
        
    Returns:
        Sanitized dictionary with sensitive fields removed
    """
    if not isinstance(exception_dict, dict):
        return exception_dict
    
    sanitized = exception_dict.copy()
    sanitized_fields = []
    
    # Recursively sanitize nested dictionaries
    for key in list(sanitized.keys()):
        # Check if this key is a sensitive field (case-insensitive)
        if isinstance(key, str) and key.lower() in SENSITIVE_FIELDS:
            sanitized_fields.append(key)
            sanitized.pop(key)
        elif isinstance(sanitized[key], dict):
            sanitized[key], nested_fields = _sanitize_dict(sanitized[key])
            sanitized_fields.extend(nested_fields)
        elif isinstance(sanitized[key], list):
            sanitized[key], list_fields = _sanitize_list(sanitized[key])
            sanitized_fields.extend(list_fields)
    
    # Audit log the sanitized field names (NOT values)
    if sanitized_fields:
        logger.info(f"Sanitized sensitive fields from exception: {sorted(set(sanitized_fields))}")
    
    return sanitized


def _sanitize_dict(data: Dict[str, Any]) -> tuple[Dict[str, Any], List[str]]:
    """Helper to sanitize a dictionary and return sanitized data and field list."""
    if not isinstance(data, dict):
        return data, []
    
    result = data.copy()
    fields = []
    
    for key in list(result.keys()):
        if isinstance(key, str) and key.lower() in SENSITIVE_FIELDS:
            fields.append(key)
            result.pop(key)
        elif isinstance(result[key], dict):
            result[key], nested_fields = _sanitize_dict(result[key])
            fields.extend(nested_fields)
        elif isinstance(result[key], list):
            result[key], list_fields = _sanitize_list(result[key])
            fields.extend(list_fields)
    
    return result, fields


def _sanitize_list(data: List[Any]) -> tuple[List[Any], List[str]]:
    """Helper to sanitize a list and return sanitized data and field list."""
    result = []
    fields = []
    
    for item in data:
        if isinstance(item, dict):
            sanitized_item, item_fields = _sanitize_dict(item)
            result.append(sanitized_item)
            fields.extend(item_fields)
        elif isinstance(item, list):
            sanitized_item, item_fields = _sanitize_list(item)
            result.append(sanitized_item)
            fields.extend(item_fields)
        else:
            result.append(item)
    
    return result, fields


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """Middleware to handle exceptions and sanitize sensitive data before serialization."""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        try:
            response = await call_next(request)
            return response
        except Exception as exc:
            # Build exception dictionary
            exception_dict = {
                "error": type(exc).__name__,
                "message": str(exc),
                "details": getattr(exc, '__dict__', {})
            }
            
            # Sanitize sensitive fields before JSON serialization
            sanitized_dict = sanitize_exception(exception_dict)
            
            # Return sanitized JSON response
            return JSONResponse(
                status_code=getattr(exc, 'status_code', 500),
                content=sanitized_dict
            )
        finally:
            # Clear request-local state
            if hasattr(request.state, '_clear'):
                request.state._clear()


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
