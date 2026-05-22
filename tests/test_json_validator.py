"""Tests for JSON serialization validation."""

import sys
sys.path.insert(0, "src")

import unittest
from src.runtime.json_validator import (
    validate_json_serializable,
    safe_json_dumps,
    sanitize_for_json,
    JSONSerializationError,
    ValidationResult,
)


class TestValidData(unittest.TestCase):
    def test_primitives(self):
        for v in [None, True, False, 42, 3.14, "hello", ""]:
            result = validate_json_serializable(v)
            self.assertTrue(result.is_valid, f"Failed for {v!r}")
    
    def test_nested_dict(self):
        data = {"a": {"b": {"c": 1}}, "d": [1, 2, 3]}
        result = validate_json_serializable(data)
        self.assertTrue(result.is_valid)
    
    def test_list_of_dicts(self):
        data = [{"id": 1}, {"id": 2}]
        result = validate_json_serializable(data)
        self.assertTrue(result.is_valid)


class TestInvalidTypes(unittest.TestCase):
    def test_set_rejected(self):
        result = validate_json_serializable({"items": {1, 2, 3}})
        self.assertFalse(result.is_valid)
        self.assertIn("set", str(result.errors[0]))
    
    def test_bytes_rejected(self):
        result = validate_json_serializable({"data": b"binary"})
        self.assertFalse(result.is_valid)
        self.assertIn("bytes", str(result.errors[0]))
    
    def test_nan_rejected(self):
        result = validate_json_serializable(float("nan"))
        self.assertFalse(result.is_valid)
        self.assertIn("NaN", str(result.errors[0]))
    
    def test_infinity_rejected(self):
        result = validate_json_serializable(float("inf"))
        self.assertFalse(result.is_valid)
        self.assertIn("Infinity", str(result.errors[0]))
    
    def test_custom_object_rejected(self):
        class Foo:
            pass
        result = validate_json_serializable(Foo())
        self.assertFalse(result.is_valid)
        self.assertIn("not JSON serializable", str(result.errors[0]))
    
    def test_non_string_dict_key(self):
        result = validate_json_serializable({1: "value"})
        self.assertFalse(result.is_valid)
        self.assertIn("dict key must be str", str(result.errors[0]))


class TestDepthLimit(unittest.TestCase):
    def test_deep_nesting_rejected(self):
        data = {"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": {"i": {"j": 1}}}}}}}}}}
        result = validate_json_serializable(data, max_depth=5)
        self.assertFalse(result.is_valid)
        self.assertIn("max depth", str(result.errors[0]))
    
    def test_within_depth_ok(self):
        data = {"a": {"b": {"c": 1}}}
        result = validate_json_serializable(data, max_depth=5)
        self.assertTrue(result.is_valid)


class TestStringLength(unittest.TestCase):
    def test_oversized_string_rejected(self):
        data = {"big": "x" * 1001}
        result = validate_json_serializable(data, max_string_length=1000)
        self.assertFalse(result.is_valid)
    
    def test_within_limit_ok(self):
        data = {"ok": "x" * 100}
        result = validate_json_serializable(data, max_string_length=1000)
        self.assertTrue(result.is_valid)


class TestSafeJsonDumps(unittest.TestCase):
    def test_valid_data(self):
        result = safe_json_dumps({"key": "value"})
        self.assertIn("key", result)
    
    def test_invalid_data_raises(self):
        with self.assertRaises(JSONSerializationError):
            safe_json_dumps({"bad": {1, 2, 3}})


class TestSanitizeForJson(unittest.TestCase):
    def test_set_to_list(self):
        result = sanitize_for_json({1, 2, 3})
        self.assertIsInstance(result, list)
        self.assertEqual(set(result), {1, 2, 3})
    
    def test_bytes_to_base64(self):
        result = sanitize_for_json(b"hello")
        self.assertIsInstance(result, str)
    
    def test_nan_to_none(self):
        result = sanitize_for_json(float("nan"))
        self.assertIsNone(result)
    
    def test_inf_to_none(self):
        result = sanitize_for_json(float("inf"))
        self.assertIsNone(result)
    
    def test_custom_object_placeholder(self):
        class Bar:
            pass
        result = sanitize_for_json(Bar())
        self.assertIn("non-serializable", result)
    
    def test_nested_sanitization(self):
        data = {"items": {1, 2}, "data": b"bin", "val": float("nan")}
        result = sanitize_for_json(data)
        self.assertIsInstance(result["items"], list)
        self.assertIsInstance(result["data"], str)
        self.assertIsNone(result["val"])


class TestValidationResult(unittest.TestCase):
    def test_bool_true(self):
        r = ValidationResult(is_valid=True)
        self.assertTrue(r)
    
    def test_bool_false(self):
        r = ValidationResult(is_valid=False, errors=[JSONSerializationError("x", "bad")])
        self.assertFalse(r)


if __name__ == "__main__":
    unittest.main()
