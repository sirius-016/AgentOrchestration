"""Webhook middleware to block disabled users."""

import json as json_lib
from typing import Any, Dict, Optional

from src.auth.user_status import (
    check_user_status,
    DisabledUserError,
    UserStatus,
)


class DisabledUserMiddleware:
    """ASGI middleware to block webhook requests from disabled users.
    
    Checks the authenticated user status before processing webhook payloads.
    Returns 403 Forbidden if the user is disabled.
    """
    
    def __init__(self, app: Any, status_provider=None):
        self.app = app
        self.status_provider = status_provider
    
    async def __call__(self, scope: Dict, receive: Any, send: Any) -> None:
        """Process request, checking user status for webhook endpoints."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        path = scope.get("path", "")
        method = scope.get("method", "")
        
        # Only check webhook endpoints
        is_webhook = "/webhook" in path and method in ("POST", "PUT")
        
        if not is_webhook:
            await self.app(scope, receive, send)
            return
        
        # Extract user identity from headers or scope
        user_id = self._extract_user_id(scope)
        if not user_id:
            # No user context, let downstream auth handle it
            await self.app(scope, receive, send)
            return
        
        # Check user status
        try:
            check_user_status(user_id, status_provider=self.status_provider)
        except DisabledUserError as e:
            response = {
                "error": {
                    "status": 403,
                    "message": str(e),
                    "code": "USER_DISABLED",
                }
            }
            response_body = json_lib.dumps(response).encode("utf-8")
            
            await send({
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", len(response_body).to_bytes(8, "big")),
                ],
            })
            await send({
                "type": "http.response.body",
                "body": response_body,
                "more_body": False,
            })
            return
        
        await self.app(scope, receive, send)
    
    @staticmethod
    def _extract_user_id(scope: Dict) -> Optional[str]:
        """Extract user ID from request scope/headers."""
        # Check scope state (set by upstream auth middleware)
        state = scope.get("state", {})
        if isinstance(state, dict):
            user = state.get("user", {})
            if isinstance(user, dict):
                return user.get("id") or user.get("user_id") or user.get("sub")
        
        # Check headers
        headers = dict(scope.get("headers", []))
        return (
            headers.get(b"x-user-id", b"").decode("utf-8") or
            headers.get(b"x-authenticated-user", b"").decode("utf-8") or
            None
        )


def require_active_user(user_id: str, is_disabled: bool = False, reason: str = None) -> None:
    """Convenience function to validate user is active.
    
    Use this in route handlers directly:
        require_active_user(user_id, user.is_disabled, user.disabled_reason)
    """
    from src.auth.user_status import validate_user_active
    validate_user_active(user_id=user_id, is_disabled=is_disabled, disabled_reason=reason)


__all__ = ["DisabledUserMiddleware", "require_active_user"]
