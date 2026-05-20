"""Tests for case-colliding environment variable detection."""
import os
import pytest
from src.common.config import Config


def test_case_collision_detection():
    """Test that case-colliding env vars raise an error."""
    # Set both AO_APP_PORT and AO_app_port
    os.environ["AO_APP_PORT"] = "8080"
    os.environ["AO_app_port"] = "9090"
    
    try:
        with pytest.raises(ValueError, match="Case-colliding environment variables"):
            Config()
    finally:
        del os.environ["AO_APP_PORT"]
        del os.environ["AO_app_port"]


def test_no_collision_same_case():
    """Test that same-case env vars work correctly."""
    os.environ["AO_APP_PORT"] = "8080"
    
    try:
        config = Config()
        assert config.get("app.port") == "8080"
    finally:
        del os.environ["AO_APP_PORT"]


def test_different_keys_no_collision():
    """Test that different normalized keys don't collide."""
    os.environ["AO_APP_PORT"] = "8080"
    os.environ["AO_APP_HOST"] = "localhost"
    
    try:
        config = Config()
        assert config.get("app.port") == "8080"
        assert config.get("app.host") == "localhost"
    finally:
        del os.environ["AO_APP_PORT"]
        del os.environ["AO_APP_HOST"]
