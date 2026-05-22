"""User status validation for webhook and API authentication."""

import os
from typing import Optional, Dict, Any
from dataclasses import dataclass


@dataclass(frozen=True)
class UserStatus:
    """Represents the status of an authenticated user."""
    user_id: str
    is_disabled: bool
    disabled_reason: Optional[str] = None
    disabled_at: Optional[str] = None


class DisabledUserError(Exception):
    """Raised when a disabled user attempts to perform an action."""
    
    def __init__(self, user_id: str, reason: Optional[str] = None):
        self.user_id = user_id
        self.reason = reason
        msg = f"User {user_id} is disabled"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)


class UserStatusCache:
    """In-memory cache for user status lookups with TTL."""
    
    def __init__(self, ttl_seconds: int = 300):
        self._cache: Dict[str, tuple] = {}  # user_id -> (UserStatus, timestamp)
        self._ttl = ttl_seconds
    
    def get(self, user_id: str) -> Optional[UserStatus]:
        """Get cached user status if not expired."""
        entry = self._cache.get(user_id)
        if entry is None:
            return None
        status, ts = entry
        if time.time() - ts > self._ttl:
            del self._cache[user_id]
            return None
        return status
    
    def set(self, user_id: str, status: UserStatus) -> None:
        """Cache user status."""
        self._cache[user_id] = (status, time.time())
    
    def invalidate(self, user_id: str) -> None:
        """Remove user from cache."""
        self._cache.pop(user_id, None)
    
    def clear(self) -> None:
        """Clear all cached entries."""
        self._cache.clear()


# Default TTL for status cache (5 minutes)
STATUS_CACHE_TTL = int(os.environ.get("USER_STATUS_CACHE_TTL", "300"))

# Global cache instance
_user_cache: Optional[UserStatusCache] = None


def get_user_cache() -> UserStatusCache:
    """Get or create the global user status cache."""
    global _user_cache
    if _user_cache is None:
        _user_cache = UserStatusCache(ttl_seconds=STATUS_CACHE_TTL)
    return _user_cache


def validate_user_active(user_id: str, is_disabled: bool, disabled_reason: Optional[str] = None) -> None:
    """Validate that a user is active and not disabled.
    
    Args:
        user_id: The user identifier
        is_disabled: Whether the user account is disabled
        disabled_reason: Optional reason for the disable
    
    Raises:
        DisabledUserError: If the user is disabled
    """
    if is_disabled:
        raise DisabledUserError(user_id=user_id, reason=disabled_reason)


def check_user_status(user_id: str, status_provider=None) -> UserStatus:
    """Check user status, using cache and optional provider.
    
    Args:
        user_id: The user identifier
        status_provider: Optional callable(user_id) -> UserStatus for fetching status
    
    Returns:
        UserStatus for the user
        
    Raises:
        DisabledUserError: If the user is disabled
    """
    cache = get_user_cache()
    
    # Check cache first
    cached = cache.get(user_id)
    if cached is not None:
        if cached.is_disabled:
            raise DisabledUserError(user_id=user_id, reason=cached.disabled_reason)
        return cached
    
    # Fetch from provider
    if status_provider is not None:
        status = status_provider(user_id)
    else:
        # Default: create active status
        status = UserStatus(user_id=user_id, is_disabled=False)
    
    # Cache the result
    cache.set(user_id, status)
    
    # Validate
    if status.is_disabled:
        raise DisabledUserError(user_id=user_id, reason=status.disabled_reason)
    
    return status


__all__ = [
    "UserStatus",
    "DisabledUserError",
    "UserStatusCache",
    "validate_user_active",
    "check_user_status",
    "get_user_cache",
]
