"""Tests for least-privilege RBAC on run cancellation (#112)."""

import pytest
import time
from src.auth.guard import AuthGuard, Role, Permission, AuthenticationError


class TestLeastPrivilegeCancellation:
    def test_admin_can_cancel_run(self):
        """Admin role should have run:cancel permission."""
        guard = AuthGuard()
        session = guard.create_session("admin-token", "ws-1", Role.ADMIN)
        assert guard.can_cancel_run(session.session_id, "ws-1") is True

    def test_operator_cannot_cancel_run(self):
        """Operator role should NOT have run:cancel permission (least-privilege)."""
        guard = AuthGuard()
        session = guard.create_session("op-token", "ws-1", Role.OPERATOR)
        assert guard.can_cancel_run(session.session_id, "ws-1") is False

    def test_viewer_cannot_cancel_run(self):
        """Viewer role should NOT have run:cancel permission."""
        guard = AuthGuard()
        session = guard.create_session("viewer-token", "ws-1", Role.VIEWER)
        assert guard.can_cancel_run(session.session_id, "ws-1") is False

    def test_expired_session_denied(self):
        """Expired sessions should be denied even with admin role."""
        guard = AuthGuard()
        session = guard.create_session("admin-token", "ws-1", Role.ADMIN, ttl=-1)  # already expired
        assert guard.can_cancel_run(session.session_id, "ws-1") is False

    def test_revoked_token_denied(self):
        """Revoked tokens should invalidate all sessions."""
        guard = AuthGuard()
        session = guard.create_session("admin-token", "ws-1", Role.ADMIN)
        guard.revoke_token("admin-token")
        assert guard.can_cancel_run(session.session_id, "ws-1") is False

    def test_workspace_mismatch_denied(self):
        """Sessions scoped to wrong workspace should be denied."""
        guard = AuthGuard()
        session = guard.create_session("admin-token", "ws-1", Role.ADMIN)
        assert guard.can_cancel_run(session.session_id, "ws-2") is False

    def test_invalid_session_denied(self):
        """Non-existent sessions should be denied."""
        guard = AuthGuard()
        assert guard.can_cancel_run("nonexistent-session", "ws-1") is False

    def test_operator_can_view_runs(self):
        """Operator should still be able to view runs."""
        guard = AuthGuard()
        session = guard.create_session("op-token", "ws-1", Role.OPERATOR)
        result = guard.authorize(session.session_id, Permission.RUN_VIEW, "ws-1")
        assert result.session_id == session.session_id

    def test_authorize_raises_on_revoked_token(self):
        """authorize() should raise AuthenticationError for revoked tokens."""
        guard = AuthGuard()
        session = guard.create_session("token", "ws-1", Role.ADMIN)
        guard.revoke_token("token")
        with pytest.raises(AuthenticationError):
            guard.authorize(session.session_id, Permission.RUN_CANCEL, "ws-1")

    def test_authorize_raises_on_permission_error(self):
        """authorize() should raise PermissionError for insufficient scope."""
        guard = AuthGuard()
        session = guard.create_session("op-token", "ws-1", Role.OPERATOR)
        with pytest.raises(PermissionError):
            guard.authorize(session.session_id, Permission.RUN_CANCEL, "ws-1")
