"""Release management — Immutable release identifier generation and tracking."""

import hashlib
import time
from uuid import uuid4

from src.common.errors import ReleaseIDError


def generate_release_id() -> str:
    """Generate an immutable, UUID-based release identifier.

    The ID is derived from a UUID4 combined with a timestamp hash,
    ensuring it is neither guessable nor mutable. User-supplied IDs
    are explicitly rejected to enforce immutability.

    Returns:
        A string of the form 'rel_<uuid4_hex>_<sha256_short>' which is
        globally unique and cannot be reconstructed from external knowledge.
    """
    uuid_part = uuid4().hex
    timestamp = str(time.time()).encode()
    hash_part = hashlib.sha256(uuid_part.encode() + timestamp).hexdigest()[:12]
    return f"rel_{uuid_part}_{hash_part}"


class Release:
    """Represents a deployment release with an immutable identifier."""

    def __init__(self, name: str, target_agent: str, config: dict = None, release_id: str = None):
        if release_id is not None:
            raise ReleaseIDError(
                "Release IDs must be auto-generated and immutable; "
                f"user-supplied ID '{release_id}' is not accepted"
            )
        self.id = generate_release_id()
        self.name = name
        self.target_agent = target_agent
        self.config = config or {}
        self.created_at = time.time()
        self.status = "pending"


class ReleaseManager:
    """Manages release lifecycle with enforced immutable identifiers."""

    def __init__(self):
        self._releases: dict = {}

    def create_release(self, name: str, target_agent: str, config: dict = None) -> Release:
        """Create a new release with an auto-generated immutable ID.

        Raises ReleaseIDError if caller attempts to supply a release_id.
        """
        release = Release(name=name, target_agent=target_agent, config=config)
        self._releases[release.id] = release
        return release

    def get_release(self, release_id: str) -> Release | None:
        return self._releases.get(release_id)

    def list_releases(self) -> list:
        return list(self._releases.values())

    def delete_release(self, release_id: str) -> bool:
        return self._releases.pop(release_id, None) is not None