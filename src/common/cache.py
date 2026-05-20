"""Local artifact download cache with checksum validation."""

import hashlib
import json
import os
import tempfile
from typing import Dict, Optional


class DownloadCache:
    """Artifact download cache that validates content digests before use.
    
    Prevents corrupt cache entries from affecting task processing by verifying
    stored content against expected metadata digests.
    """

    def __init__(self, cache_dir: Optional[str] = None, max_size_mb: int = 1024):
        self._cache_dir = cache_dir or os.path.join(tempfile.gettempdir(), "artifact_cache")
        self._max_size_bytes = max_size_mb * 1024 * 1024
        self._metadata_file = os.path.join(self._cache_dir, "_metadata.json")
        os.makedirs(self._cache_dir, exist_ok=True)
        self._load_metadata()

    def _load_metadata(self) -> None:
        """Load cache metadata from disk."""
        if os.path.exists(self._metadata_file):
            with open(self._metadata_file, "r") as f:
                self._metadata: Dict[str, Dict] = json.load(f)
        else:
            self._metadata = {}

    def _save_metadata(self) -> None:
        """Persist cache metadata to disk."""
        with open(self._metadata_file, "w") as f:
            json.dump(self._metadata, f)

    def _compute_digest(self, file_path: str, algorithm: str = "sha256") -> str:
        """Compute digest of a file."""
        h = hashlib.new(algorithm)
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    def _verify_digest(self, file_path: str, expected_digest: str, algorithm: str = "sha256") -> bool:
        """Verify file digest matches expected value."""
        actual = self._compute_digest(file_path, algorithm)
        return actual == expected_digest

    def store(self, key: str, content: bytes, expected_digest: str, algorithm: str = "sha256") -> str:
        """Store content in cache with digest metadata.
        
        Args:
            key: Cache key for the artifact
            content: File content bytes
            expected_digest: Expected digest of the content
            algorithm: Hash algorithm (sha256, md5, etc.)
        
        Returns:
            Path to the cached file
        """
        # Write to temp file first
        fd, temp_path = tempfile.mkstemp(dir=self._cache_dir)
        try:
            os.write(fd, content)
            os.close(fd)

            # Verify digest before committing
            actual_digest = self._compute_digest(temp_path, algorithm)
            if actual_digest != expected_digest:
                os.unlink(temp_path)
                raise ValueError(
                    f"Content digest mismatch: expected {expected_digest}, got {actual_digest}"
                )

            # Commit: move to final location
            cache_path = os.path.join(self._cache_dir, key)
            if os.path.exists(cache_path):
                os.unlink(cache_path)
            os.rename(temp_path, cache_path)

            # Update metadata
            self._metadata[key] = {
                "digest": expected_digest,
                "algorithm": algorithm,
                "size": len(content),
            }
            self._save_metadata()
            return cache_path

        except Exception:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise

    def get(self, key: str) -> Optional[bytes]:
        """Retrieve and verify cached artifact.
        
        Returns None if cache miss or digest mismatch.
        Raises exception on corrupt cache entry.
        """
        if key not in self._metadata:
            return None

        cache_path = os.path.join(self._cache_dir, key)
        if not os.path.exists(cache_path):
            # Cache file missing: evict and return None
            self.evict(key)
            return None

        meta = self._metadata[key]
        if not self._verify_digest(cache_path, meta["digest"], meta.get("algorithm", "sha256")):
            # Corrupt cache entry: evict and raise
            self.evict(key)
            raise ValueError(f"Cache entry corrupt: {key}")

        with open(cache_path, "rb") as f:
            return f.read()

    def has_valid(self, key: str) -> bool:
        """Check if cache has a valid (verified) entry."""
        if key not in self._metadata:
            return False
        cache_path = os.path.join(self._cache_dir, key)
        if not os.path.exists(cache_path):
            return False
        meta = self._metadata[key]
        return self._verify_digest(cache_path, meta["digest"], meta.get("algorithm", "sha256"))

    def evict(self, key: str) -> bool:
        """Remove a cache entry (including corrupt ones)."""
        if key in self._metadata:
            del self._metadata[key]
            self._save_metadata()
        cache_path = os.path.join(self._cache_dir, key)
        if os.path.exists(cache_path):
            os.unlink(cache_path)
            return True
        return False

    def clear(self) -> int:
        """Clear all cache entries. Returns number of entries removed."""
        count = len(self._metadata)
        for key in list(self._metadata.keys()):
            self.evict(key)
        return count


_cache_instance: Optional[DownloadCache] = None


def get_cache() -> DownloadCache:
    """Get the global cache instance."""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = DownloadCache()
    return _cache_instance
