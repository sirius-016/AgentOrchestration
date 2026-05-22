"""Tests for admin response model enforcement."""

import sys
sys.path.insert(0, "src")

import unittest
from unittest.mock import patch
from src.api.admin_response_model import (
    ResponseModel,
    AdminResponseModelError,
    enforce_response_model,
    require_response_model,
    skip_response_model,
    register_admin_response_model,
    ADMIN_RESPONSE_MODELS,
)


class TestResponseModel(unittest.TestCase):
    def test_validate_success(self):
        model = ResponseModel("Test", required_fields=["id", "name"])
        errors = model.validate({"id": 1, "name": "test"})
        self.assertEqual(errors, [])
    
    def test_validate_missing_required(self):
        model = ResponseModel("Test", required_fields=["id", "name"])
        errors = model.validate({"id": 1})
        self.assertEqual(len(errors), 1)
        self.assertIn("name", errors[0])
    
    def test_validate_optional_ok(self):
        model = ResponseModel("Test", required_fields=["id"], optional_fields=["extra"])
        errors = model.validate({"id": 1})
        self.assertEqual(errors, [])
    
    def test_validate_extra_fields_ok(self):
        model = ResponseModel("Test", required_fields=["id"])
        errors = model.validate({"id": 1, "extra": "allowed"})
        self.assertEqual(errors, [])


class TestEnforceResponseModel(unittest.TestCase):
    def test_enforce_valid_response(self):
        # Should not raise
        enforce_response_model("admin.user.list", {
            "users": [], "total": 0, "page": 1
        })
    
    def test_enforce_invalid_response_raises(self):
        with self.assertRaises(AdminResponseModelError) as ctx:
            enforce_response_model("admin.user.list", {"users": []})
        self.assertIn("missing required field", str(ctx.exception))
    
    def test_enforce_unregistered_endpoint_raises(self):
        with self.assertRaises(AdminResponseModelError) as ctx:
            enforce_response_model("admin.unknown", {})
        self.assertIn("no response model registered", str(ctx.exception))
    
    @patch('src.api.admin_response_model.ENFORCE_ADMIN_RESPONSE_MODEL', False)
    def test_enforce_disabled_skips_validation(self):
        # Should not raise even with invalid data
        enforce_response_model("admin.user.list", {})


class TestRequireResponseModel(unittest.TestCase):
    def test_decorator_valid(self):
        @require_response_model("admin.user.list")
        def list_users():
            return {"users": [], "total": 0, "page": 1}
        result = list_users()
        self.assertEqual(result["total"], 0)
    
    def test_decorator_invalid_raises(self):
        @require_response_model("admin.user.list")
        def bad_list():
            return {"users": []}
        with self.assertRaises(AdminResponseModelError):
            bad_list()
    
    def test_decorator_non_dict_passes(self):
        @require_response_model("admin.user.list")
        def returns_string():
            return "not a dict"
        result = returns_string()
        self.assertEqual(result, "not a dict")


class TestSkipResponseModel(unittest.TestCase):
    def test_skip_decorator(self):
        @skip_response_model
        def custom_endpoint():
            return {"anything": "goes"}
        self.assertTrue(hasattr(custom_endpoint, '_skip_response_model'))


class TestRegisterResponseModel(unittest.TestCase):
    def test_register_new_model(self):
        model = ResponseModel("Custom", required_fields=["data"])
        register_admin_response_model("admin.custom", model)
        self.assertIn("admin.custom", ADMIN_RESPONSE_MODELS)
        
        # Should now validate
        enforce_response_model("admin.custom", {"data": "test"})


class TestStandardModels(unittest.TestCase):
    def test_user_list_model_exists(self):
        self.assertIn("admin.user.list", ADMIN_RESPONSE_MODELS)
    
    def test_user_get_model_exists(self):
        self.assertIn("admin.user.get", ADMIN_RESPONSE_MODELS)
    
    def test_run_list_model_exists(self):
        self.assertIn("admin.run.list", ADMIN_RESPONSE_MODELS)
    
    def test_config_model_exists(self):
        self.assertIn("admin.config.get", ADMIN_RESPONSE_MODELS)
    
    def test_health_model_exists(self):
        self.assertIn("admin.health.check", ADMIN_RESPONSE_MODELS)


if __name__ == "__main__":
    unittest.main()
