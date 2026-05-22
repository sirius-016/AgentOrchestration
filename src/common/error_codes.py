"""Consistent error codes for API validation failures."""

from enum import IntEnum
from typing import Dict, Type, Any


class ErrorCode(IntEnum):
    """HTTP status codes for consistent error handling."""
    BAD_REQUEST = 400
    UNAUTHORIZED = 401
    FORBIDDEN = 403
    NOT_FOUND = 404
    METHOD_NOT_ALLOWED = 405
    CONFLICT = 409
    UNPROCESSABLE_ENTITY = 422
    INTERNAL_SERVER_ERROR = 500
    SERVICE_UNAVAILABLE = 503


# Exception -> HTTP status code mapping
EXCEPTION_STATUS_MAP: Dict[str, int] = {
    "ValueError": ErrorCode.BAD_REQUEST,
    "ValidationError": ErrorCode.BAD_REQUEST,
    "KeyError": ErrorCode.BAD_REQUEST,
    "TypeError": ErrorCode.BAD_REQUEST,
    "FileNotFoundError": ErrorCode.NOT_FOUND,
    "PermissionError": ErrorCode.FORBIDDEN,
    "TimeoutError": ErrorCode.SERVICE_UNAVAILABLE,
    "ConnectionError": ErrorCode.SERVICE_UNAVAILABLE,
    "Exception": ErrorCode.INTERNAL_SERVER_ERROR,
}


def get_status_for_exception(exc: Exception) -> int:
    """Return HTTP status code for an exception.
    
    Args:
        exc: The exception to map
        
    Returns:
        HTTP status code (int)
    """
    exc_type = type(exc).__name__
    
    # Check exact match first
    if exc_type in EXCEPTION_STATUS_MAP:
        return EXCEPTION_STATUS_MAP[exc_type]
    
    # Check for subclass matches
    for cls in type(exc).__mro__:
        if cls.__name__ in EXCEPTION_STATUS_MAP:
            return EXCEPTION_STATUS_MAP[cls.__name__]
    
    # Default: 500
    return ErrorCode.INTERNAL_SERVER_ERROR


def make_error_response(status_code: int, message: str, details: Any = None) -> Dict:
    """Create a consistent error response dict.
    
    Args:
        status_code: HTTP status code
        message: Human-readable error message
        details: Optional additional error details
        
    Returns:
        Dict with "error" key containing status, message, details
    """
    response = {
        "error": {
            "status": status_code,
            "message": message,
        }
    }
    if details is not None:
        response["error"]["details"] = details
    return response


__all__ = ["ErrorCode", "EXCEPTION_STATUS_MAP", "get_status_for_exception", "make_error_response"]
