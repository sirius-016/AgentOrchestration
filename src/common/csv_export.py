"""CSV export utilities with spreadsheet formula escaping.

Prevents CSV injection attacks by neutralizing formula-like values
when exporting data intended for spreadsheet applications.
"""

import csv
import io
from typing import Any, Dict, List


# Characters that trigger formula interpretation in spreadsheets
FORMULA_TRIGGERS = frozenset({
    "=",  # All spreadsheet formulas start with =
    "+",  # + followed by expression is treated as formula
    "-",  # - followed by expression is treated as formula
    "\t",  # Tab prefix triggers formula
    "\r",  # Carriage return prefix
    "\n",  # Newline in cell value
    "@",  # @function calls in Excel/LibreOffice
})

ESCAPE_CHAR = "'"  # Prepend single quote to neutralize without data loss


def _is_formula_risk(value: str) -> bool:
    """Check if a string value risks formula interpretation."""
    if not isinstance(value, str) or len(value) == 0:
        return False
    first_char = value[0]
    return first_char in FORMULA_TRIGGERS


def escape_csv_value(value: Any) -> str:
    """Escape a single value for safe CSV export.

    If the value is a string that starts with a formula trigger character,
    prepend a single quote to neutralize it (visible in spreadsheet,
    data preserved as string, not evaluated as formula).
    For other values, convert to string normally.
    """
    if not isinstance(value, str):
        return str(value)

    if _is_formula_risk(value):
        return ESCAPE_CHAR + value
    return value


def escape_csv_row(row: List[Any]) -> List[str]:
    """Escape all values in a row for safe CSV export."""
    return [escape_csv_value(v) for v in row]


def escape_csv_dict(row: Dict[str, Any], fieldnames: List[str]) -> List[str]:
    """Escape a dict as a CSV row.

    Args:
        row: Dict mapping field names to values
        fieldnames: Column order (keys to include)

    Returns:
        List of escaped string values
    """
    return [escape_csv_value(row.get(field, "")) for field in fieldnames]


class SafeCSVWriter:
    """CSV writer that automatically escapes formula-like values.

    Use this for any CSV export that may be opened in spreadsheet software.
    """

    def __init__(self, output: io.TextIOWriter, fieldnames: List[str]):
        self._writer = csv.writer(output)
        self._fieldnames = fieldnames
        # Write header
        self._writer.writerow(fieldnames)

    def writerow(self, row: Dict[str, Any]) -> None:
        """Write a row, escaping formula-like values automatically."""
        escaped = escape_csv_dict(row, self._fieldnames)
        self._writer.writerow(escaped)

    def writerows(self, rows: List[Dict[str, Any]]) -> None:
        """Write multiple rows."""
        for row in rows:
            self.writerow(row)


def to_csv_string(rows: List[Dict[str, Any]], fieldnames: List[str]) -> str:
    """Convert a list of dicts to a CSV string with formula escaping.

    Args:
        rows: List of dicts to convert
        fieldnames: Column order

    Returns:
        CSV-formatted string with formula characters escaped
    """
    output = io.StringIO()
    writer = SafeCSVWriter(output, fieldnames)
    writer.writerows(rows)
    return output.getvalue()


# ---- JSON-safe alternative ----

def to_json_string(rows: List[Dict[str, Any]]) -> str:
    """Convert rows to JSON, preserving original values.

    JSON exports do NOT need formula escaping since spreadsheet
    software reads them as structured data, not formulas.
    """
    import json
    return json.dumps(rows, indent=2, default=str)
