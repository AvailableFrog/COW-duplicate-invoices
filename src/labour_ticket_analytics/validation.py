"""Import issues: what is wrong with individual cells and business IDs.

Validation never drops, repairs or reinterprets a Ticket. Each problem becomes
an issue naming the Excel row, the field and a code, and the Ticket stays in
the Snapshot with its raw cells intact (PRD section 8).
"""

from __future__ import annotations

import datetime as dt
import re
from typing import TYPE_CHECKING, Any, Iterable

from labour_ticket_analytics.schema import REQUIRED_COLUMNS

if TYPE_CHECKING:
    from labour_ticket_analytics.workbook import Cell, Ticket

NUMBER_COLUMNS = ("Regular Hours", "Overtime", "Double Time", "Job Work Pay", "Rate")
DATE_COLUMNS = ("Date", "Modified", "Created", "Date Approved")
IDENTIFIER_COLUMNS = ("Job Number", "ID")
BUSINESS_ID_COLUMNS = ("Ticket Number", "ID")
APPROVAL_STATUSES = ("Approved", "Pending", "Rejected")
DIGITS = re.compile(r"\d+")

# An ISO 8601 calendar date, optionally with a time of day: the only date text
# that reads the same in every locale.
ISO_DATE_TEXT = re.compile(r"\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?)?")


def issue(excel_row: int, field_name: str, code: str, message: str) -> dict[str, Any]:
    return {"excel_row": excel_row, "field": field_name, "code": code, "message": message}


def validate(tickets: Iterable[Ticket]) -> list[dict[str, Any]]:
    """Every import issue, ordered by Excel row and then by column position."""
    tickets = list(tickets)
    rows_by_id = _rows_by_business_id(tickets)
    issues: list[dict[str, Any]] = []
    for ticket in tickets:
        for cell in ticket.cells:
            if cell.field in BUSINESS_ID_COLUMNS:
                problem = _business_id_problem(cell, ticket.excel_row, rows_by_id[cell.field])
            else:
                problem = None
            problem = problem or _cell_problem(cell)
            if problem is not None:
                issues.append(issue(ticket.excel_row, cell.field, *problem))
    return issues


def _business_id(cell: Cell) -> Any:
    """The value a business ID is compared by, or None when it cannot be compared.

    Ticket Number is text and is compared exactly as written; ID is compared
    as the whole number it holds, so 500 and "500" are the same ID.
    """
    if _is_missing(cell):
        return None
    if cell.field == "ID":
        return whole_number(cell)
    return str(cell.value)


def _rows_by_business_id(tickets: list[Ticket]) -> dict[str, dict[Any, list[int]]]:
    rows: dict[str, dict[Any, list[int]]] = {name: {} for name in BUSINESS_ID_COLUMNS}
    for ticket in tickets:
        for cell in ticket.cells:
            if cell.field in BUSINESS_ID_COLUMNS:
                key = _business_id(cell)
                if key is not None:
                    rows[cell.field].setdefault(key, []).append(ticket.excel_row)
    return rows


def _business_id_problem(cell: Cell, excel_row: int, rows_by_id: dict[Any, list[int]]) -> tuple[str, str] | None:
    if _is_missing(cell):
        return "missing_business_id", f"{cell.field} is missing; the Ticket is still identified by its Excel row"
    key = _business_id(cell)
    others = [row for row in rows_by_id.get(key, []) if row != excel_row]
    if others:
        listed = ", ".join(str(row) for row in others)
        return "repeated_business_id", (
            f"{cell.field} {key} also appears at Excel row{'s' if len(others) > 1 else ''} {listed}"
        )
    return None


def _is_missing(cell: Cell) -> bool:
    return cell.raw_type == "blank" or (cell.raw_type == "str" and cell.value.strip() == "")


def _cell_problem(cell: Cell) -> tuple[str, str] | None:
    if _is_missing(cell):
        if cell.field in REQUIRED_COLUMNS:
            return "missing_value", f"{cell.field} is empty, but every Ticket needs it"
        return None
    if cell.raw_type == "formula":
        return "formula_not_evaluated", (
            f"{cell.field} holds the formula {cell.value}, which is kept as text and never evaluated"
        )
    if cell.raw_type == "error":
        return "error_value", f"{cell.field} holds the spreadsheet error {cell.value}"
    if cell.field in NUMBER_COLUMNS and not _is_number(cell):
        return "invalid_number", f"{cell.field} is {_shown(cell)}, which is not a number"
    if cell.field in IDENTIFIER_COLUMNS and whole_number(cell) is None:
        return "invalid_number", (
            f"{cell.field} is {_shown(cell)}, which is not a whole number written without grouping separators"
        )
    if cell.field == "Approval Status" and cell.value not in APPROVAL_STATUSES:
        return "unknown_status", (
            f"Approval Status is {_shown(cell)}, which is not one of {', '.join(APPROVAL_STATUSES)}; it is not coerced"
        )
    if cell.field == "Keyed" and cell.raw_type != "bool":
        return "unknown_boolean", f"Keyed is {_shown(cell)}, which is not a true or false cell; it is not coerced"
    if cell.field in DATE_COLUMNS and not _is_date(cell):
        if cell.raw_type == "str":
            return "invalid_date", (
                f"{cell.field} is {_shown(cell)}, which is not an ISO 8601 date; "
                "its day and month order is not guessed"
            )
        return "invalid_date", f"{cell.field} is {_shown(cell)}, which is not a date"
    return None


def _is_number(cell: Cell) -> bool:
    return cell.raw_type in ("int", "float")


def whole_number(cell: Cell) -> int | None:
    """The integer an identifier cell holds, or None when it holds anything else."""
    if cell.raw_type == "int":
        return cell.value
    if cell.raw_type == "float" and cell.value.is_integer():
        return int(cell.value)
    if cell.raw_type == "str" and DIGITS.fullmatch(cell.value):
        return int(cell.value)
    return None


def _is_date(cell: Cell) -> bool:
    if cell.raw_type in ("datetime", "date"):
        return True
    if cell.raw_type != "str" or not ISO_DATE_TEXT.fullmatch(cell.value):
        return False
    try:
        dt.datetime.fromisoformat(cell.value)
    except ValueError:
        return False
    return True


def _shown(cell: Cell) -> str:
    return repr(cell.value) if cell.raw_type == "str" else f"a {cell.raw_type} value ({cell.value})"
