"""Authentication, session, and RBAC guard for operator tokens."""

import hashlib
import logging
import time
from enum import Enum
from typing import Dict, FrozenSet, List, Optional, Set

logger = logging.getLogger(__name__)


class Role(Enum):
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


class Permission(Enum):
    RUN_CANCEL = "run:cancel"
    RUN_VIEW = "run:view"
    RUN_START = "run:start"
    AGENT_MANAGE = "agent:manage"
    AGENT_VIEW = "agent:view"
    DEPLOY = "deploy"


# Role-to-permission mapping (least-privilege)
ROLE_PERMISSIONS: Dict[Role, FrozenSet[Permission]] = {
    Role.ADMIN: frozenset(Permission),
    Role.OPERATOR: frozenset({
        Permission.RUN_VIEW,
        Permission.RUN_START,
        Permission.AGENT_VIEW,
    }),
    Role.VIEWER: frozenset({
        Permission.RUN_VIEW,
        Permission.AGENT_VIEW,
    }),
}


class Session:
    """Represents an authenticated session with scoped permissions."""

    def __init__(self, session_id: str, workspace_id: str, role: Role,
                 token_hash: str, expires_at: float):
        self.session_id = session_id
        self.workspace_id = workspace_id
        self.role = role
        self.token_hash = token_hash
        self.expires_at = expires_at
        self.permissions = ROLE_PERMISSIONS[role]

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    def has_permission(self, permission: Permission) -> bool:
        return permission in self.permissions and not self.is_expired

    def belongs_to_workspace(self, workspace_id: str) -> bool:
        return self.workspace_id == workspace_id


class AuthGuard:
    """Central authorization guard that enforces least-privilege scopes.

    Every lookup, mutation, and dispatch decision is scoped to the
    authenticated workspace and active role. Stale, revoked, or
    insufficiently scoped principals are denied.
    """

    def __init__(self):
        self._sessions: Dict[str, Session] = {}
        self._revoked_tokens: Set[str] = set()

    def create_session(self, token: str, workspace_id: str, role: Role,
                       ttl: float = 3600) -> Session:
        """Create a new authenticated session."""
        token_hash = hashlib.sha256(token.encode()).hexdigest()[:32]
        session = Session(
            session_id=hashlib.sha256(f"{token_hash}:{time.time()}".encode()).hexdigest()[:16],
            workspace_id=workspace_id,
            role=role,
            token_hash=token_hash,
            expires_at=time.time() + ttl,
        )
        self._sessions[session.session_id] = session
        logger.info(f"Session created: {session.session_id} role={role.value} workspace={workspace_id}")
        return session

    def revoke_token(self, token: str) -> None:
        """Revoke a token, invalidating all sessions using it."""
        token_hash = hashlib.sha256(token.encode()).hexdigest()[:32]
        self._revoked_tokens.add(token_hash)
        # Remove all sessions using this token
        revoked_sessions = [
            sid for sid, s in self._sessions.items()
            if s.token_hash == token_hash
        ]
        for sid in revoked_sessions:
            del self._sessions[sid]
            logger.info(f"Session revoked: {sid}")

    def authorize(self, session_id: str, permission: Permission,
                  workspace_id: Optional[str] = None) -> Session:
        """Authorize a session for a specific permission and optionally a workspace.

        Raises:
            AuthenticationError: If session is invalid, expired, or revoked
            PermissionError: If session lacks the required permission
        """
        session = self._sessions.get(session_id)

        if session is None:
            logger.warning(f"Authorization failed: session {session_id} not found")
            raise AuthenticationError("Invalid session")

        if session.token_hash in self._revoked_tokens:
            logger.warning(f"Authorization failed: token revoked for session {session_id}")
            raise AuthenticationError("Token has been revoked")

        if session.is_expired:
            logger.warning(f"Authorization failed: session {session_id} expired")
            raise AuthenticationError("Session has expired")

        if workspace_id and not session.belongs_to_workspace(workspace_id):
            logger.warning(
                f"Authorization failed: session {session_id} workspace mismatch "
                f"(required={workspace_id}, actual={session.workspace_id})"
            )
            raise PermissionError(
                f"Session does not belong to workspace {workspace_id}"
            )

        if not session.has_permission(permission):
            logger.warning(
                f"Authorization failed: session {session_id} lacks permission "
                f"{permission.value} (role={session.role.value})"
            )
            raise PermissionError(
                f"Role '{session.role.value}' does not have permission '{permission.value}'"
            )

        return session

    def can_cancel_run(self, session_id: str, workspace_id: str) -> bool:
        """Check if a session is authorized to cancel a run.

        Only ADMIN role has run:cancel permission (least-privilege).
        OPERATOR and VIEWER are denied.
        """
        try:
            self.authorize(session_id, Permission.RUN_CANCEL, workspace_id)
            return True
        except (AuthenticationError, PermissionError):
            return False


class AuthenticationError(Exception):
    """Raised when authentication fails."""
    pass
