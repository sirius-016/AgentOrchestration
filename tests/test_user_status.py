"""Tests for user status validation and disabled user blocking."""

import sys
sys.path.insert(0, "src")

import unittest
from unittest.mock import MagicMock, AsyncMock, patch
from src.auth.user_status import (
    UserStatus,
    DisabledUserError,
    UserStatusCache,
    validate_user_active,
    check_user_status,
    get_user_cache,
)
from src.api.webhook_auth_middleware import DisabledUserMiddleware, require_active_user


class TestValidateUserActive(unittest.TestCase):
    def test_active_user_passes(self):
        validate_user_active("user1", is_disabled=False)
    
    def test_disabled_user_raises(self):
        with self.assertRaises(DisabledUserError) as ctx:
            validate_user_active("user1", is_disabled=True, disabled_reason="TOS violation")
        self.assertIn("TOS violation", str(ctx.exception))
    
    def test_disabled_user_no_reason(self):
        with self.assertRaises(DisabledUserError) as ctx:
            validate_user_active("user1", is_disabled=True)
        self.assertIn("disabled", str(ctx.exception))


class TestUserStatusCache(unittest.TestCase):
    def setUp(self):
        self.cache = UserStatusCache(ttl_seconds=1)
    
    def test_set_and_get(self):
        status = UserStatus(user_id="u1", is_disabled=False)
        self.cache.set("u1", status)
        result = self.cache.get("u1")
        self.assertEqual(result.user_id, "u1")
        self.assertFalse(result.is_disabled)
    
    def test_expired_entry(self):
        status = UserStatus(user_id="u1", is_disabled=False)
        self.cache.set("u1", status)
        import time as _t
        _t.sleep(1.1)
        self.assertIsNone(self.cache.get("u1"))
    
    def test_invalidate(self):
        status = UserStatus(user_id="u1", is_disabled=True)
        self.cache.set("u1", status)
        self.cache.invalidate("u1")
        self.assertIsNone(self.cache.get("u1"))
    
    def test_clear(self):
        self.cache.set("u1", UserStatus(user_id="u1", is_disabled=False))
        self.cache.set("u2", UserStatus(user_id="u2", is_disabled=True))
        self.cache.clear()
        self.assertIsNone(self.cache.get("u1"))
        self.assertIsNone(self.cache.get("u2"))


class TestCheckUserStatus(unittest.TestCase):
    def setUp(self):
        self.cache = UserStatusCache(ttl_seconds=300)
    
    def test_active_user_returns_status(self):
        def provider(uid):
            return UserStatus(user_id=uid, is_disabled=False)
        result = check_user_status("u1", status_provider=provider)
        self.assertFalse(result.is_disabled)
    
    def test_disabled_user_raises(self):
        def provider(uid):
            return UserStatus(user_id=uid, is_disabled=True, disabled_reason="banned")
        with self.assertRaises(DisabledUserError):
            check_user_status("u1", status_provider=provider)
    
    def test_cached_disabled_raises(self):
        cache = get_user_cache()
        cache.clear()
        def provider(uid):
            return UserStatus(user_id=uid, is_disabled=True, disabled_reason="spam")
        # First call - should raise and cache
        with self.assertRaises(DisabledUserError):
            check_user_status("u1", status_provider=provider)
        # Second call - should use cache
        with self.assertRaises(DisabledUserError):
            check_user_status("u1", status_provider=provider)
        cache.clear()


class TestDisabledUserMiddleware(unittest.TestCase):
    def test_non_webhook_passes(self):
        app = AsyncMock()
        mw = DisabledUserMiddleware(app)
        import asyncio
        asyncio.get_event_loop().run_until_complete(
            mw({"type": "http", "path": "/api/runs", "method": "GET"}, AsyncMock(), AsyncMock())
        )
        app.assert_called_once()
    
    def test_webhook_disabled_user_blocked(self):
        app = AsyncMock()
        mw = DisabledUserMiddleware(app, status_provider=lambda uid: UserStatus(uid, True, "banned"))
        import asyncio
        loop = asyncio.get_event_loop()
        scope = {"type": "http", "path": "/webhook/handler", "method": "POST", "state": {"user": {"id": "u1"}}}
        send = AsyncMock()
        loop.run_until_complete(mw(scope, AsyncMock(), send))
        # Should send 403, not call app
        app.assert_not_called()
        start_call = send.call_args_list[0]
        self.assertEqual(start_call[0][0]["status"], 403)


if __name__ == "__main__":
    unittest.main()
