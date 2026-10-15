"""Read a labour-ticket workbook into an immutable Snapshot.

Every cell keeps its raw value and raw type, its Excel row and its original
dataframe index (Excel row minus 2), in the workbook's original order. The
workbook is opened read-only and formulas, macros, links and embedded content
are never executed. Nothing is ever written back.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import openpyxl

from labour_ticket_analytics.schema import (
    disabled_features,
    missing_optional_columns,
    missing_required_columns,
    repeated_schema_columns,
)
from labour_ticket_analytics.validation import validate

FINGERPRINT_ALGORITHM = "sha256"
HEADER_ROW = 1
FIRST_DATA_ROW = HEADER_ROW + 1

# Raw types a cell can carry. "blank" is an empty cell; "zero" never appears
# here because a numeric zero is just an "int" or "float" whose value is 0.
RawType = str


@dataclass(frozen=True)
class Cell:
    field: str
    position: int
    raw_type: RawType
    value: Any
    number_format: str | None


@dataclass(frozen=True)
class Ticket:
    excel_row: int
    dataframe_index: int
    cells: tuple[Cell, ...]


@dataclass(frozen=True)
class Snapshot:
    fingerprint: str
    fingerprint_algorithm: str
    workbook_name: str
    sheet: str
    fields: tuple[str, ...]
    tickets: tuple[Ticket, ...]
    imported_at: dt.datetime
    import_issues: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    @property
    def missing_optional_columns(self) -> list[str]:
        return missing_optional_columns(self.fields)

    @property
    def disabled_features(self) -> list[dict[str, Any]]:
        return disabled_features(self.fields)

    @property
    def row_count(self) -> int:
        return len(self.tickets)

    @property
    def field_count(self) -> int:
        return len(self.fields)


class WorkbookError(Exception):
    """The workbook cannot become a Snapshot; the message says why."""


def fingerprint_workbook(path: Path) -> str:
    digest = hashlib.new(FINGERPRINT_ALGORITHM)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def import_workbook(path: Path, workbook_name: str | None = None) -> Snapshot:
    """Read the workbook into a Snapshot; `workbook_name` is the name to show when the file is stored under another
    (a browser upload). Formulas are kept as text, external links are not loaded and macros are never run."""
    if not path.is_file():
        raise WorkbookError(f"workbook not found: {path}")
    name = workbook_name or path.name
    fingerprint = fingerprint_workbook(path)
    try:
        book = openpyxl.load_workbook(path, read_only=True, data_only=False, keep_links=False)
    except Exception as error:  # openpyxl raises several unrelated types
        raise WorkbookError(f"workbook could not be read: {name} ({error})") from error
    try:
        found = _find_data_sheet(book)
        if found is None:
            raise WorkbookError(
                f"workbook has no data sheet: {name} has no worksheet with a header row in row {HEADER_ROW}"
            )
        sheet, fields, rows = found
        missing = missing_required_columns(fields)
        if missing:
            raise WorkbookError(
                f"data sheet {sheet.title!r} in {name} is missing required "
                f"column{'s' if len(missing) > 1 else ''}: {', '.join(missing)}"
            )
        repeated = repeated_schema_columns(fields)
        if repeated:
            raise WorkbookError(
                f"data sheet {sheet.title!r} in {name} names a column more than once, "
                f"so its mapping is ambiguous: {', '.join(repeated)}"
            )
        tickets = _read_tickets(rows, fields)
    finally:
        book.close()
    return Snapshot(
        fingerprint=fingerprint,
        fingerprint_algorithm=FINGERPRINT_ALGORITHM,
        workbook_name=name,
        sheet=sheet.title,
        fields=fields,
        tickets=tuple(tickets),
        imported_at=dt.datetime.now(dt.timezone.utc),
        import_issues=tuple(validate(tickets)),
    )


def _find_data_sheet(book):
    """The data sheet with its header row and remaining rows, or None when there is none.

    The data sheet is the first worksheet whose header row carries every
    required column. When no worksheet does, it is the first worksheet with
    any header at all, so the refusal names the columns that sheet lacks. An
    empty or titled cover sheet is skipped; chart sheets are never considered.
    """
    fallback = None
    for sheet in book.worksheets:
        rows = sheet.iter_rows(min_row=HEADER_ROW)
        header = next(rows, None)
        if not header or all(getattr(cell, "value", None) in (None, "") for cell in header):
            continue
        fields = tuple(_header_name(cell.value, index) for index, cell in enumerate(header))
        if not missing_required_columns(fields):
            return sheet, fields, rows
        if fallback is None:
            fallback = (sheet, fields, rows)
    return fallback


def _header_name(value: Any, index: int) -> str:
    if value is None or str(value) == "":
        return f"Column {index + 1}"
    return str(value)


def _read_tickets(rows, fields: tuple[str, ...]) -> list[Ticket]:
    """One Ticket per sheet row after the header, in sheet order.

    The Excel row comes from the position in the sheet, not from a cell: a
    fully blank row yields placeholder cells with no row attribute, and it
    must still be preserved as a Ticket so later rows keep their numbers.
    Only trailing blank rows, which carry nothing, are dropped.
    """
    tickets: list[Ticket] = []
    for excel_row, row in enumerate(rows, start=FIRST_DATA_ROW):
        cells = tuple(
            _read_cell(fields[position], position, row[position] if position < len(row) else None)
            for position in range(len(fields))
        )
        tickets.append(Ticket(excel_row=excel_row, dataframe_index=excel_row - FIRST_DATA_ROW, cells=cells))
    while tickets and all(cell.raw_type == "blank" for cell in tickets[-1].cells):
        tickets.pop()
    return tickets


def _read_cell(field_name: str, position: int, cell) -> Cell:
    if cell is None or getattr(cell, "value", None) is None:
        return Cell(field_name, position, "blank", None, None)
    raw_type, value = classify(cell.value, getattr(cell, "data_type", None))
    number_format = getattr(cell, "number_format", None) if raw_type != "blank" else None
    return Cell(field_name, position, raw_type, value, number_format)


def classify(value: Any, data_type: str | None = None) -> tuple[RawType, Any]:
    """Name the raw type of a cell value without changing the value.

    Booleans come before integers because bool subclasses int. A numeric zero
    stays a number; it is never read as midnight.
    """
    if value is None:
        return "blank", None
    if data_type == "f":
        return "formula", str(value)
    if data_type == "e":
        return "error", str(value)
    if isinstance(value, bool):
        return "bool", value
    if isinstance(value, int):
        return "int", value
    if isinstance(value, float):
        return "float", value
    if isinstance(value, dt.datetime):
        return "datetime", value
    if isinstance(value, dt.date):
        return "date", value
    if isinstance(value, dt.time):
        return "time", value
    if isinstance(value, dt.timedelta):
        return "duration", value
    if isinstance(value, str):
        return "str", value
    return "str", str(value)
