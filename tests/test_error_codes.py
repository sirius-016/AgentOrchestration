"""Tests for consistent error code handling."""

import sys
sys.path.insert(0, "src")

import unittest
from src.common.error_codes import (
    ErrorCode,
    EXCEPTION_STATUS_MAP,
    get_status_for_exception,
    make_error_response,
)


class TestErrorCode(unittest.TestCase):
    """Test ErrorCode enum."""

    def test_bad_request_code(self):
        """BAD_REQUEST should be 400."""
        self.assertEqual(ErrorCode.BAD_REQUEST, 400)

    def test_not_found_code(self):
        """NOT_FOUND should be 404."""
        self.assertEqual(ErrorCode.NOT_FOUND, 404)

    def test_internal_server_error_code(self):
        """INTERNAL_SERVER_ERROR should be 500."""
        self.assertEqual(ErrorCode.INTERNAL_SERVER_ERROR, 500)


class TestGetStatusForException(unittest.TestCase):
    """Test get_status_for_exception()."""

    def test_value_error_returns_400(self):
        """ValueError should map to 400."""
        exc = ValueError("invalid input")
        self.assertEqual(get_status_for_exception(exc), 400)

    def test_file_not_found_returns_404(self):
        """FileNotFoundError should map to 404."""
        exc = FileNotFoundError("file not found")
        self.assertEqual(get_status_for_exception(exc), 404)

    def test_permission_error_returns_403(self):
        """PermissionError should map to 403."""
        exc = PermissionError("access denied")
        self.assertEqual(get_status_for_exception(exc), 403)

    def test_generic_exception_returns_500(self):
        """Generic Exception should map to 500."""
        exc = Exception("something went wrong")
        self.assertEqual(get_status_for_exception(exc), 500)

    def test_timeout_error_returns_503(self):
        """TimeoutError should map to 503."""
        exc = TimeoutError("timed out")
        self.assertEqual(get_status_for_exception(exc), 503)


class TestMakeErrorResponse(unittest.TestCase):
    """Test make_error_response()."""

    def test_basic_response(self):
        """Should create dict with status and message."""
        resp = make_error_response(400, "Bad request")
        self.assertEqual(resp["error"]["status"], 400)
        self.assertEqual(resp["error"]["message"], "Bad request")

    def test_response_with_details(self):
        """Should include details when provided."""
        resp = make_error_response(404, "Not found", details={"resource": "user"})
        self.assertEqual(resp["error"]["details"], {"resource": "user"})

    def test_response_without_details(self):
        """Should not include details key when not provided."""
        resp = make_error_response(500, "Server error")
        self.assertNotIn("details", resp["error"])


if __name__ == "__main__":
    unittest.main()
