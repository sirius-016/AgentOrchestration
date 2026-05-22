"""Response model enforcement for admin-only API endpoints."""

import os
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass
from functools import wraps


# Require admin endpoints to use explicit response models
ENFORCE_ADMIN_RESPONSE_MODEL = os.environ.get("ENFORCE_ADMIN_RESPONSE_MODEL", "true").lower() == "true"


class AdminResponseModelError(Exception):
    """Raised when an admin endpoint violates response model policy."""
    
    def __init__(self, endpoint: str, reason: str):
        self.endpoint = endpoint
        self.reason = reason
        super().__init__(f"Admin endpoint {endpoint}: {reason}")


@dataclass
class ResponseModel:
    """Schema definition for API response validation."""
    name: str
    required_fields: List[str]
    optional_fields: List[str] = None
    
    def __post_init__(self):
        if self.optional_fields is None:
            self.optional_fields = []
    
    def validate(self, data: Dict[str, Any]) -> List[str]:
        """Validate data against model. Returns list of errors."""
        errors = []
        for field in self.required_fields:
            if field not in data:
                errors.append(f"missing required field: {field}")
        return errors


# Standard response models for admin endpoints
ADMIN_RESPONSE_MODELS: Dict[str, ResponseModel] = {
    "admin.user.list": ResponseModel(
        name="UserListResponse",
        required_fields=["users", "total", "page"],
        optional_fields=["per_page", "has_more"]
    ),
    "admin.user.get": ResponseModel(
        name="UserDetailResponse", 
        required_fields=["id", "email", "status"],
        optional_fields=["created_at", "updated_at", "roles"]
    ),
    "admin.run.list": ResponseModel(
        name="RunListResponse",
        required_fields=["runs", "total"],
        optional_fields=["page", "filters"]
    ),
    "admin.config.get": ResponseModel(
        name="ConfigResponse",
        required_fields=["config"],
        optional_fields=["version", "last_modified"]
    ),
    "admin.health.check": ResponseModel(
        name="HealthCheckResponse",
        required_fields=["status", "components"],
        optional_fields=["version", "uptime"]
    ),
}


def get_response_model(endpoint: str) -> Optional[ResponseModel]:
    """Get the response model for an admin endpoint."""
    return ADMIN_RESPONSE_MODELS.get(endpoint)


def enforce_response_model(endpoint: str, response_data: Dict[str, Any]) -> None:
    """Validate that response conforms to the registered model.
    
    Raises:
        AdminResponseModelError: If validation fails and enforcement is enabled.
    """
    if not ENFORCE_ADMIN_RESPONSE_MODEL:
        return
    
    model = get_response_model(endpoint)
    if model is None:
        # No model registered - require explicit registration
        raise AdminResponseModelError(
            endpoint, 
            f"no response model registered. Add to ADMIN_RESPONSE_MODELS or use @skip_response_model"
        )
    
    errors = model.validate(response_data)
    if errors:
        raise AdminResponseModelError(
            endpoint,
            f"validation failed: {'; '.join(errors)}"
        )


def require_response_model(model_name: str):
    """Decorator to enforce a specific response model on an admin endpoint.
    
    Usage:
        @require_response_model("admin.user.list")
        def list_users():
            return {"users": [...], "total": 10, "page": 1}
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)
            if isinstance(result, dict):
                model = ADMIN_RESPONSE_MODELS.get(model_name)
                if model:
                    errors = model.validate(result)
                    if errors and ENFORCE_ADMIN_RESPONSE_MODEL:
                        raise AdminResponseModelError(model_name, '; '.join(errors))
            return result
        return wrapper
    return decorator


def skip_response_model(func: Callable) -> Callable:
    """Decorator to opt out of response model enforcement.
    
    Usage:
        @skip_response_model
        def custom_admin_endpoint():
            return {"custom": "data"}
    """
    func._skip_response_model = True
    return func


def register_admin_response_model(endpoint: str, model: ResponseModel) -> None:
    """Register a response model for an admin endpoint."""
    ADMIN_RESPONSE_MODELS[endpoint] = model


__all__ = [
    "AdminResponseModelError",
    "ResponseModel",
    "ADMIN_RESPONSE_MODELS",
    "enforce_response_model",
    "require_response_model",
    "skip_response_model",
    "register_admin_response_model",
    "get_response_model",
    "ENFORCE_ADMIN_RESPONSE_MODEL",
]
