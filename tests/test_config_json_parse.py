"""Tests for config file JSON parsing with path context."""
import json
import pytest
import tempfile
import os
from src.common.config import Config


def test_json_decode_error_includes_path():
    """Test that malformed JSON includes the file path in the error message."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write("{ invalid json }")
        temp_path = f.name
    
    try:
        config = Config()
        with pytest.raises(json.JSONDecodeError, match=temp_path):
            config.load(temp_path)
    finally:
        os.unlink(temp_path)


def test_valid_json_loads():
    """Test that valid JSON loads correctly."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({"key": "value"}, f)
        temp_path = f.name
    
    try:
        config = Config()
        config.load(temp_path)
        assert config.get("key") == "value"
    finally:
        os.unlink(temp_path)


def test_json_error_message_format():
    """Test that JSON error message has the expected format."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write("true,")  # Invalid JSON
        temp_path = f.name
    
    try:
        config = Config()
        with pytest.raises(json.JSONDecodeError) as exc_info:
            config.load(temp_path)
        
        error_msg = str(exc_info.value)
        assert temp_path in error_msg
        assert "line" in error_msg.lower() or "pos" in error_msg.lower()
    finally:
        os.unlink(temp_path)
