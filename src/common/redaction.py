"""Redaction validation for JSON export."""

import json as json_lib
from typing import Any, Dict, List, Set

# Fields that must be redacted before export
SENSITIVE_FIELDS: Set[str] = {
    "password", "token", "secret", "key",
    "authorization", "cookie", "session",
    "api_key", "api_secret", "credential",
    "private_key", "access_token", "refresh_token",
}


class RedactionValidationError(Exception):
    """Raised when unredacted sensitive fields found in export."""
    pass


def _check_value(key: str, value: Any, path: str = "") -> List[str]:
    """Recursively check for unredacted sensitive fields."""
    issues = []
    full_key = f"{path}.{key}" if path else key
    
    key_lower = key.lower()
    for sf in SENSITIVE_FIELDS:
        if sf in key_lower:
            if value not in (None, "", "***", "REDACTED", "***REDACTED***"):
                issues.append(f"Unredacted field: {full_key}")
    
    if isinstance(value, dict):
        for k, v in value.items():
            issues.extend(_check_value(k, v, full_key))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            issues.extend(_check_value(f"{key}[{i}]", item, path))
    
    return issues


def validate_redaction(data: Any, context: str = "") -> None:
    """Validate that no sensitive fields remain unredacted in data.
    
    Args:
        data: Data to validate (dict, list, or scalar)
        context: Optional context string for error messages
    
    Raises:
        RedactionValidationError: If unredacted sensitive fields found
    """
    issues = []
    
    if isinstance(data, dict):
        for key, value in data.items():
            issues.extend(_check_value(key, value))
    elif isinstance(data, list):
        for i, item in enumerate(data):
            issues.extend(_check_value(f"[{i}]", item))
    
    if issues:
        msg = "Redaction validation failed"
        if context:
            msg += f" in {context}"
        msg += ":
" + "
".join(f"  - {issue}" for issue in issues)
        raise RedactionValidationError(msg)


def safe_json_export(data: Any, context: str = "") -> str:
    """Validate redaction then serialize to JSON.
    
    Args:
        data: Data to export
        context: Optional context for error messages
    
    Returns:
        JSON string
    
    Raises:
        RedactionValidationError: If unredacted sensitive fields found
    """
    validate_redaction(data, context)
    return json_lib.dumps(data, default=str)


__all__ = ["SENSITIVE_FIELDS", "RedactionValidationError", "validate_redaction", "safe_json_export"]
