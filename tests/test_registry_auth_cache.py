"""Tests for registry authorization cache with permission-change recheck."""
import pytest
import time
from src.agent.registry import AgentRegistry, AuthorizationError


def test_authorization_cached():
    """Test that authorization is cached after first check."""
    reg = AgentRegistry(auth_cache_age=60.0)
    aid = reg.register("test-agent", "test.type")

    # Open by default
    result1 = reg.check_authorization("caller-1", aid)
    assert result1 is True

    # Second call uses cache (no change in permissions)
    result2 = reg.check_authorization("caller-1", aid)
    assert result2 is True


def test_authorization_recheck_force():
    """Test that recheck=True bypasses cache."""
    reg = AgentRegistry(auth_cache_age=60.0)
    aid = reg.register("test-agent", "test.type")

    result1 = reg.check_authorization("caller-1", aid, recheck=False)
    result2 = reg.check_authorization("caller-1", aid, recheck=True)
    assert result1 == result2  # Same result, but recheck hit the actual check


def test_permission_change_invalidates_cache():
    """Test that permission changes invalidate cached auth decisions."""
    reg = AgentRegistry(auth_cache_age=60.0)
    aid = reg.register("test-agent", "test.type")

    # Initially open
    assert reg.check_authorization("caller-x", aid) is True

    # Restrict to specific callers
    reg.set_permissions(aid, {"caller-y"})
    # Cache for "caller-x" should be invalidated
    result = reg.check_authorization("caller-x", aid)
    assert result is False


def test_set_permissions_with_recheck():
    """Test that set_permissions causes fresh recheck."""
    reg = AgentRegistry(auth_cache_age=60.0)
    aid = reg.register("test-agent", "test.type")

    reg.set_permissions(aid, {"caller-a"})

    # After set_permissions, cache is invalidated
    # caller-a should be allowed, new caller-b should be denied
    assert reg.check_authorization("caller-a", aid) is True
    assert reg.check_authorization("caller-b", aid) is False


def test_on_permission_change_invalidates():
    """Test that on_permission_change invalidates cache."""
    reg = AgentRegistry(auth_cache_age=60.0)
    aid = reg.register("test-agent", "test.type")

    reg.check_authorization("caller-z", aid)

    reg.on_permission_change(aid)

    # Should re-check and find same result (open registry)
    assert reg.check_authorization("caller-z", aid) is True


def test_check_authorization_unknown_agent():
    """Test that checking unknown agent raises AuthorizationError."""
    reg = AgentRegistry()

    with pytest.raises(AuthorizationError):
        reg.check_authorization("caller", "nonexistent-agent-id")


def test_permission_version_bump():
    """Test that bumping permission version invalidates cache."""
    reg = AgentRegistry(auth_cache_age=60.0)
    aid = reg.register("test-agent", "test.type")

    # Cache a decision
    reg.check_authorization("caller-1", aid)

    # Bump version
    reg._auth_cache.bump_permission_version(aid)

    # Next check should be fresh (no cache hit)
    result = reg.check_authorization("caller-1", aid)
    assert result is True


def test_cache_stale_after_max_age():
    """Test that cache entries become stale after max_age."""
    reg = AgentRegistry(auth_cache_age=0.1)  # 100ms
    aid = reg.register("test-agent", "test.type")

    reg.check_authorization("caller-1", aid)

    time.sleep(0.15)

    # Should be considered stale and re-checked
    cached = reg._auth_cache.get("caller-1", aid, "access")
    assert cached is None  # Stale = not in cache
