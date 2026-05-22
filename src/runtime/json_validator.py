"""JSON serialization validation for runtime payloads."""

import json
import os
from typing import Any, Optional, List, Tuple
from dataclasses import dataclass, field


# Max allowed nesting depth for JSON payloads
DEFAULT_MAX_DEPTH = 20
MAX_JSON_DEPTH = int(os.environ.get("MAX_JSON_DEPTH", DEFAULT_MAX_DEPTH))

# Max allowed string length per value
DEFAULT_MAX_STRING_LENGTH = 1_000_000  # 1MB
MAX_JSON_STRING_LENGTH = int(os.environ.get("MAX_JSON_STRING_LENGTH", DEFAULT_MAX_STRING_LENGTH))

# Allowed primitive types for JSON serialization
JSON_SAFE_TYPES = (str, int, float, bool, type(None))


class JSONSerializationError(Exception):
    """Raised when data fails JSON serialization validation."""
    
    def __init__(self, path: str, reason: str, value_type: str = ""):
        self.path = path
        self.reason = reason
        self.value_type = value_type
        msg = f"JSON serialization error at {path}: {reason}"
        if value_type:
            msg += f" (got {value_type})"
        super().__init__(msg)


@dataclass
class ValidationResult:
    """Result of JSON serialization validation."""
    is_valid: bool
    errors: List[JSONSerializationError] = field(default_factory=list)
    
    def __bool__(self):
        return self.is_valid


def validate_json_serializable(data: Any, max_depth: int = MAX_JSON_DEPTH,
                                max_string_length: int = MAX_JSON_STRING_LENGTH,
                                path: str = "root") -> ValidationResult:
    """Validate that data can be safely JSON serialized.
    
    Checks for:
    - Non-JSON-serializable types (set, bytes, datetime, custom objects)
    - Excessive nesting depth
    - Oversized string values
    - Circular reference indicators (repeated object ids)
    - NaN/Infinity float values
    
    Args:
        data: The data to validate
        max_depth: Maximum allowed nesting depth
        max_string_length: Maximum allowed string length
        path: Current path in the data structure (for error reporting)
    
    Returns:
        ValidationResult with is_valid flag and any errors found
    """
    errors = []
    _seen = set()
    _validate_recursive(data, max_depth, max_string_length, path, 0, errors, _seen)
    return ValidationResult(is_valid=len(errors) == 0, errors=errors)


def _validate_recursive(data: Any, max_depth: int, max_string_length: int,
                         path: str, depth: int, errors: List[JSONSerializationError],
                         seen: set) -> None:
    """Recursively validate data structure."""
    # Check depth
    if depth > max_depth:
        errors.append(JSONSerializationError(path, f"exceeds max depth {max_depth}"))
        return
    
    # Check for None
    if data is None:
        return
    
    # Check primitive types
    if isinstance(data, bool):
        return  # bool must be checked before int
    
    if isinstance(data, int):
        return
    
    if isinstance(data, float):
        import math
        if math.isnan(data):
            errors.append(JSONSerializationError(path, "NaN is not JSON serializable", "float"))
        elif math.isinf(data):
            errors.append(JSONSerializationError(path, "Infinity is not JSON serializable", "float"))
        return
    
    if isinstance(data, str):
        if len(data) > max_string_length:
            errors.append(JSONSerializationError(
                path, f"string length {len(data)} exceeds max {max_string_length}", "str"))
        return
    
    # Check for non-JSON types
    if isinstance(data, (set, frozenset)):
        errors.append(JSONSerializationError(path, "set is not JSON serializable, use list", type(data).__name__))
        return
    
    if isinstance(data, bytes):
        errors.append(JSONSerializationError(path, "bytes is not JSON serializable", "bytes"))
        return
    
    # Check for circular references (by object id for mutable containers)
    obj_id = id(data)
    if obj_id in seen:
        errors.append(JSONSerializationError(path, "circular reference detected"))
        return
    
    # Check for dict
    if isinstance(data, dict):
        seen.add(obj_id)
        for key, value in data.items():
            if not isinstance(key, str):
                errors.append(JSONSerializationError(
                    f"{path}.key", f"dict key must be str, got {type(key).__name__}"))
            else:
                _validate_recursive(value, max_depth, max_string_length,
                                   f"{path}.{key}", depth + 1, errors, seen)
        seen.discard(obj_id)
        return
    
    # Check for list/tuple
    if isinstance(data, (list, tuple)):
        seen.add(obj_id)
        for i, item in enumerate(data):
            _validate_recursive(item, max_depth, max_string_length,
                               f"{path}[{i}]", depth + 1, errors, seen)
        seen.discard(obj_id)
        return
    
    # Unknown type - not JSON serializable
    errors.append(JSONSerializationError(
        path, f"type {type(data).__name__} is not JSON serializable", type(data).__name__))


def safe_json_dumps(data: Any, **kwargs) -> str:
    """JSON dumps with pre-validation. Raises JSONSerializationError on invalid data."""
    result = validate_json_serializable(data)
    if not result.is_valid:
        raise result.errors[0]
    return json.dumps(data, **kwargs)


def sanitize_for_json(data: Any) -> Any:
    """Attempt to coerce data into JSON-serializable form.
    
    - Converts sets to lists
    - Converts bytes to base64 strings
    - Replaces NaN/Infinity with None
    - Strips non-serializable values with a placeholder
    """
    if data is None:
        return None
    if isinstance(data, bool):
        return data
    if isinstance(data, int):
        return data
    if isinstance(data, float):
        import math
        if math.isnan(data) or math.isinf(data):
            return None
        return data
    if isinstance(data, str):
        return data
    if isinstance(data, (set, frozenset)):
        return [sanitize_for_json(item) for item in data]
    if isinstance(data, bytes):
        import base64 as b64mod
        return b64mod.b64encode(data).decode('ascii')
    if isinstance(data, dict):
        return {str(k): sanitize_for_json(v) for k, v in data.items()}
    if isinstance(data, (list, tuple)):
        return [sanitize_for_json(item) for item in data]
    # Fallback: string representation
    return f"<non-serializable: {type(data).__name__}>"


__all__ = [
    "JSONSerializationError",
    "ValidationResult",
    "validate_json_serializable",
    "safe_json_dumps",
    "sanitize_for_json",
    "MAX_JSON_DEPTH",
    "MAX_JSON_STRING_LENGTH",
]
