"""Normalized Ticket values: what metrics and filters read instead of raw cells.

Each value is the one validation accepted, or None when the cell is blank,
invalid, a formula, an error, or its column is absent from the workbook. None
is never replaced by zero or an empty string, so a metric can exclude the
unusable calculation and disclose it. The raw cells stay untouched beside
these values.
"""

from __future__ import annotations

from typing import Any

from labour_ticket_analytics.validation import APPROVAL_STATUSES, date_value, number_value, whole_number
from labour_ticket_analytics.workbook import Cell, Ticket

# Storage column -> DuckDB type, in table order.
COLUMNS = {
    "snapshot_fingerprint": "VARCHAR",
    "excel_row": "INTEGER",
    "ticket_number": "VARCHAR",
    "employee_name": "VARCHAR",
    "employee_label": "VARCHAR",
    "job_number": "BIGINT",
    "job_name": "VARCHAR",
    "status": "VARCHAR",
    "keyed": "BOOLEAN",
    "work_date": "TIMESTAMP",
    "created": "TIMESTAMP",
    "date_approved": "TIMESTAMP",
    "time_key": "VARCHAR",
    "regular_hours": "DOUBLE",
    "overtime": "DOUBLE",
    "double_time": "DOUBLE",
    "job_work_pay": "DOUBLE",
    "rate": "DOUBLE",
    "supervisor": "VARCHAR",
    "occupation": "VARCHAR",
}


def employee_label(cell: Cell | None) -> str | None:
    """Employee text after trim, case-fold and whitespace collapse: a label, not a verified person."""
    text = _text(cell)
    return None if text is None else normalize_label(text)


def normalize_label(text: str) -> str | None:
    """A name as an employee label: trimmed, case-folded, whitespace collapsed; None when nothing is left."""
    return " ".join(text.split()).casefold() or None


def time_key(cell: Cell | None) -> str | None:
    """The Time cell as the Strict repeat rule compares it: text after trim, case-fold and whitespace collapse.

    A typed cell keeps its raw type in the key, so the number 0 equals only
    another 0 and never the text "0" or a blank. Blank, formula and error
    cells have no key and never satisfy equality.
    """
    if cell is None or cell.raw_type in ("blank", "formula", "error"):
        return None
    if cell.raw_type == "str":
        text = " ".join(cell.value.split()).casefold()
        return f"text:{text}" if text else None
    value = cell.value.isoformat() if hasattr(cell.value, "isoformat") else repr(cell.value)
    return f"{cell.raw_type}:{value}"


def ticket_values(fingerprint: str, ticket: Ticket) -> tuple[Any, ...]:
    """One row of normalized values, in COLUMNS order."""
    cells = {cell.field: cell for cell in ticket.cells}

    def read(field_name: str, reader) -> Any:
        cell = cells.get(field_name)
        return None if cell is None else reader(cell)

    status = read("Approval Status", lambda cell: cell.value if cell.raw_type == "str" else None)
    return (
        fingerprint,
        ticket.excel_row,
        _text(cells.get("Ticket Number")),
        _text(cells.get("Employee")),
        employee_label(cells.get("Employee")),
        read("Job Number", whole_number),
        _text(cells.get("Job Name")),
        status if status in APPROVAL_STATUSES else None,
        read("Keyed", lambda cell: cell.value if cell.raw_type == "bool" else None),
        read("Date", date_value),
        read("Created", date_value),
        read("Date Approved", date_value),
        time_key(cells.get("Time")),
        read("Regular Hours", number_value),
        read("Overtime", number_value),
        read("Double Time", number_value),
        read("Job Work Pay", number_value),
        read("Rate", number_value),
        _text(cells.get("Supervisor")),
        _text(cells.get("Occupation")),
    )


def _text(cell: Cell | None) -> str | None:
    """A grouping label as written; blank, formula and error cells have none."""
    if cell is None or cell.raw_type in ("blank", "formula", "error"):
        return None
    text = str(cell.value)
    return text if text.strip() else None
