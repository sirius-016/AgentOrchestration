"""Tests for config branch protection against scalar replacement."""
import pytest
from src.common.config import Config
import os
import json
import tempfile


def test_set_nested_creates_path():
    """Test that valid nested keys create missing path components."""
    c = Config()
    c._set_nested("a.b.c", "value")
    assert c.get("a.b.c") == "value"


def test_set_nested_deepens_existing():
    """Test that setting a deeper key under an existing dict works."""
    c = Config()
    c._set_nested("x.y", "hello")
    c._set_nested("x.y.z", "world")
    assert c.get("x.y.z") == "world"


def test_set_nested_blocks_scalar_replacement():
    """Test that a scalar cannot be replaced by a nested key."""
    c = Config()
    c.set("scalar", "I am a string")

    with pytest.raises(ValueError, match="path component 'scalar' is a scalar"):
        c._set_nested("scalar.nested", "value")


def test_set_nested_blocks_intermediate_scalar():
    """Test that intermediate scalars block nested setting."""
    c = Config()
    c.set("top.middle", "a string")

    # Trying to set "top.middle.deep.value" fails because
    # the path "top" -> "middle" is a scalar
    with pytest.raises(ValueError, match="path component 'middle' is a scalar"):
        c._set_nested("top.middle.deep.value", "x")


def test_set_nested_allows_same_key_override():
    """Test that overwriting the same leaf key is allowed."""
    c = Config()
    c.set("a.b", "first")
    c.set("a.b", "second")
    assert c.get("a.b") == "second"


def test_scalar_leaf_override_via_env():
    """Test that AO_ prefix cannot override scalars with nested paths."""
    c = Config()
    # Simulate env var loading with a scalar that blocks nested path
    c._data = {"forbidden": "scalar value"}

    # Manually set _data first (simulating config file load)
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump({"forbidden": "scalar value"}, f)
        f.flush()
        fname = f.name

    try:
        c.load(fname)
        # Now try to set nested via env override
        with pytest.raises(ValueError):
            c._set_nested("forbidden.deep.nested", "bad-value")
    finally:
        os.unlink(fname)


def test_load_with_env_override_safe():
    """Test that loading config with env overrides works when paths are valid."""
    c = Config()

    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump({"valid": {"nested": "original"}}, f)
        f.flush()
        fname = f.name

    try:
        c.load(fname)
        # Override a valid nested key via env
        c._set_nested("valid.nested", "overridden")
        assert c.get("valid.nested") == "overridden"
    finally:
        os.unlink(fname)
