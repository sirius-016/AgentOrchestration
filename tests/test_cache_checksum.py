"""Tests for checksum-validated download cache."""
import pytest
import os
import tempfile
from src.common.cache import DownloadCache


@pytest.fixture
def cache():
    """Fresh cache for each test."""
    tmpdir = tempfile.mkdtemp()
    return DownloadCache(cache_dir=tmpdir)


def test_store_and_retrieve(cache):
    """Test basic store and retrieve."""
    content = b"hello world"
    digest = "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"  # sha256
    
    path = cache.store("test1", content, digest)
    assert os.path.exists(path)
    
    retrieved = cache.get("test1")
    assert retrieved == content


def test_corrupt_cache_raises(cache):
    """Test that corrupt cache entries are detected and evicted."""
    content = b"original content"
    digest = "sha256_of_original"  # fake digest for this test
    
    # Store with wrong digest
    path = cache.store("test2", content, digest)
    
    # Manually corrupt the file
    with open(path, "wb") as f:
        f.write(b"corrupted content")
    
    # get() should raise
    with pytest.raises(ValueError, match="corrupt"):
        cache.get("test2")
    
    # Entry should be evicted
    assert not cache.has_valid("test2")


def test_missing_file_evicted(cache):
    """Test that missing cache files are evicted."""
    content = b"test data"
    digest = "digest123"
    
    cache.store("test3", content, digest)
    # Manually delete the file
    os.unlink(os.path.join(cache._cache_dir, "test3"))
    
    # get() returns None (evicted silently)
    assert cache.get("test3") is None


def test_has_valid(cache):
    """Test has_valid() returns correct status."""
    content = b"test"
    digest = "digest"
    
    assert not cache.has_valid("nonexistent")
    
    cache.store("test4", content, digest)
    assert cache.has_valid("test4")


def test_evict(cache):
    """Test explicit eviction."""
    content = b"test"
    cache.store("test5", content, "digest")
    assert cache.has_valid("test5")
    
    cache.evict("test5")
    assert not cache.has_valid("test5")


def test_clear(cache):
    """Test clearing all entries."""
    for i in range(5):
        cache.store(f"key{i}", f"content{i}".encode(), f"digest{i}")
    
    count = cache.clear()
    assert count == 5
    assert len(cache._metadata) == 0
