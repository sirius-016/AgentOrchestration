"""Tests for CSV formula escaping."""
import pytest
from src.common.csv_export import (
    escape_csv_value, escape_csv_row, escape_csv_dict,
    SafeCSVWriter, to_csv_string, to_json_string,
    FORMULA_TRIGGERS, ESCAPE_CHAR,
    _is_formula_risk,
)
import io


def test_escape_formula_equals():
    """Test that = prefixed values are escaped."""
    assert escape_csv_value("=SUM(A1:A10)") == "'=SUM(A1:A10)"


def test_escape_formula_plus():
    """Test that + prefixed values are escaped."""
    assert escape_csv_value("+1+2") == "'+1+2"


def test_escape_formula_minus():
    """Test that - prefixed values are escaped."""
    assert escape_csv_value("-1-2") == "'-1-2"


def test_escape_formula_at():
    """Test that @ prefixed values are escaped."""
    assert escape_csv_value("@DDEREF") == "'@DDEREF"


def test_escape_formula_tab():
    """Test that tab-prefixed values are escaped."""
    assert escape_csv_value("\tHello") == "'\tHello"


def test_preserve_normal_text():
    """Test that normal text is not escaped."""
    assert escape_csv_value("Hello World") == "Hello World"
    assert escape_csv_value("2024-01-01") == "2024-01-01"


def test_preserve_numbers():
    """Test that numeric values are not escaped."""
    assert escape_csv_value(42) == "42"
    assert escape_csv_value(3.14) == "3.14"


def test_escape_csv_row():
    """Test row escaping."""
    row = ["=HYPERLINK(...)", "Normal text", 42]
    escaped = escape_csv_row(row)
    assert escaped[0].startswith(ESCAPE_CHAR)
    assert escaped[1] == "Normal text"
    assert escaped[2] == "42"


def test_safe_csv_writer():
    """Test SafeCSVWriter automatically escapes."""
    output = io.StringIO()
    writer = SafeCSVWriter(output, ["name", "value"])
    writer.writerow({"name": "=cmd|'/c calc'", "value": "100"})

    content = output.getvalue()
    assert "=cmd" not in content  # Should be escaped
    assert "cmd" in content  # But data is preserved


def test_to_csv_string():
    """Test to_csv_string with formula data."""
    rows = [
        {"id": 1, "formula": "=1+1"},
        {"id": 2, "formula": "Normal text"},
    ]
    csv = to_csv_string(rows, ["id", "formula"])
    assert "=1+1" in csv  # Data preserved
    assert "\'" in csv or csv[csv.find("=1+1") - 1] == "'"  # Escaped


def test_to_json_preserves_formulas():
    """Test that JSON export preserves original values (no escaping needed)."""
    rows = [{"id": 1, "formula": "=1+1"}]
    json_str = to_json_string(rows)
    assert "=1+1" in json_str  # Original preserved, not escaped
    assert "\'" not in json_str  # No formula escaping in JSON


def test_is_formula_risk():
    """Test formula risk detection."""
    assert _is_formula_risk("=SUM(A1)") is True
    assert _is_formula_risk("+cmd|'/c") is True
    assert _is_formula_risk("Hello") is False
    assert _is_formula_risk("") is False
    assert _is_formula_risk(42) is False  # Non-string returns False
