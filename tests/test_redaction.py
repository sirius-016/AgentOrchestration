"""Tests for redaction validation in JSON export."""


import sys
sys.path.insert(0, "src")

import unittest
from src.common.redaction import (
    validate_redaction,
    safe_json_export,
    RedactionValidationError,
    SENSITIVE_FIELDS,
)


class TestRedactionValidation(unittest.TestCase):
    """Test cases for validate_redaction."""

    def test_clean_data_passes(self):
        """Clean data should pass validation."""
        data = {"name": "test", "value": 42}
        validate_redaction(data)

    def test_unredacted_password_fails(self):
        """Unredacted password should fail."""
        data = {"password": "secret123"}
        with self.assertRaises(RedactionValidationError):
            validate_redaction(data)

    def test_redacted_password_passes(self):
        """Properly redacted password should pass."""
        data = {"password": "***"}
        validate_redaction(data)

    def test_redacted_password_redacted_passes(self):
        """REDACTED password should pass."""
        data = {"password": "REDACTED"}
        validate_redaction(data)

    def test_nested_unredacted_fails(self):
        """Nested unredacted fields should fail."""
        data = {"user": {"token": "abc123"}}
        with self.assertRaises(RedactionValidationError):
            validate_redaction(data)

    def test_list_unredacted_fails(self):
        """Unredacted fields in lists should fail."""
        data = [{"secret": "mysecret"}]
        with self.assertRaises(RedactionValidationError):
            validate_redaction(data)

    def test_safe_json_export_valid(self):
        """safe_json_export should return valid JSON for clean data."""
        data = {"name": "test"}
        result = safe_json_export(data)
        self.assertEqual(result, '{"name": "test"}')

    def test_safe_json_export_invalid(self):
        """safe_json_export should raise on invalid data."""
        data = {"api_key": "leaked"}
        with self.assertRaises(RedactionValidationError):
            safe_json_export(data)

    def test_empty_data_passes(self):
        """Empty dict should pass."""
        validate_redaction({})

    def test_none_values_pass(self):
        """None values should pass (treated as redacted)."""
        data = {"password": None}
        validate_redaction(data)

    def test_sensitive_fields_list(self):
        """SENSITIVE_FIELDS should contain expected fields."""
        self.assertIn("password", SENSITIVE_FIELDS)
        self.assertIn("token", SENSITIVE_FIELDS)
        self.assertIn("secret", SENSITIVE_FIELDS)


if __name__ == "__main__":
    unittest.main()
