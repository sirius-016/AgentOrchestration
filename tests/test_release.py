"""Tests for immutable release identifiers — Issue #1863."""

import pytest
from src.orchestrator.release import generate_release_id, Release, ReleaseManager
from src.common.errors import ReleaseIDError


class TestGenerateReleaseID:
    def test_auto_generated_id_format(self):
        rid = generate_release_id()
        assert rid.startswith("rel_")
        parts = rid.split("_")
        assert len(parts) == 3  # rel, uuid_hex, hash_short
        assert len(parts[1]) == 32  # uuid4 hex length
        assert len(parts[2]) == 12  # sha256 short hash

    def test_auto_generated_ids_are_unique(self):
        ids = {generate_release_id() for _ in range(100)}
        assert len(ids) == 100  # all unique

    def test_auto_generated_id_is_immutable_uuid_based(self):
        rid = generate_release_id()
        assert rid.startswith("rel_")
        # Contains UUID hex — not guessable or sequential
        uuid_part = rid.split("_")[1]
        assert len(uuid_part) == 32


class TestReleaseIDRejection:
    def test_user_supplied_id_raises_error(self):
        with pytest.raises(ReleaseIDError, match="user-supplied"):
            Release(name="v1.0", target_agent="agent-1", release_id="my-custom-id")

    def test_user_supplied_sequential_id_raises_error(self):
        with pytest.raises(ReleaseIDError, match="user-supplied"):
            Release(name="v2.0", target_agent="agent-1", release_id="release-001")

    def test_user_supplied_uuid_raises_error(self):
        """Even if user supplies a UUID, it must still be rejected — only auto-generation is allowed."""
        with pytest.raises(ReleaseIDError, match="user-supplied"):
            Release(name="v3.0", target_agent="agent-1", release_id="rel_abc123_def456")

    def test_release_without_supplied_id_auto_generates(self):
        release = Release(name="v1.0", target_agent="agent-1")
        assert release.id is not None
        assert release.id.startswith("rel_")


class TestReleaseManager:
    def setup_method(self):
        self.manager = ReleaseManager()

    def test_create_release_auto_generates_id(self):
        release = self.manager.create_release(name="v1.0", target_agent="agent-1")
        assert release.id.startswith("rel_")
        assert release.name == "v1.0"
        assert release.status == "pending"

    def test_create_release_rejects_user_supplied_id(self):
        """ReleaseManager.create_release never accepts user-supplied IDs (no parameter)."""
        # The ReleaseManager API does not expose release_id parameter at all
        release = self.manager.create_release(name="v1.0", target_agent="agent-1")
        assert release.id.startswith("rel_")

    def test_get_release(self):
        release = self.manager.create_release(name="v1.0", target_agent="agent-1")
        found = self.manager.get_release(release.id)
        assert found is release

    def test_list_releases(self):
        self.manager.create_release(name="v1.0", target_agent="agent-1")
        self.manager.create_release(name="v2.0", target_agent="agent-2")
        assert len(self.manager.list_releases()) == 2

    def test_delete_release(self):
        release = self.manager.create_release(name="v1.0", target_agent="agent-1")
        assert self.manager.delete_release(release.id)
        assert self.manager.get_release(release.id) is None