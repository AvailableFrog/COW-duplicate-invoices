"""DuckDB tables for Snapshots.

Snapshot tables are rebuilt from the workbook on every launch and hold the
source Tickets as cells with raw value, raw type, Excel row and dataframe
index. Local review data (a later ticket) lives in a separate file and is
never mixed into these tables.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import threading
from typing import Any, Iterable

import duckdb

from labour_ticket_analytics.workbook import Cell, Snapshot

SCHEMA = """
CREATE TABLE snapshots (
    fingerprint VARCHAR PRIMARY KEY,
    fingerprint_algorithm VARCHAR NOT NULL,
    workbook_name VARCHAR NOT NULL,
    sheet VARCHAR NOT NULL,
    row_count INTEGER NOT NULL,
    field_count INTEGER NOT NULL,
    fields VARCHAR[] NOT NULL,
    imported_at VARCHAR NOT NULL,
    missing_optional_columns VARCHAR[] NOT NULL,
    disabled_features JSON NOT NULL
);
CREATE TABLE tickets (
    snapshot_fingerprint VARCHAR NOT NULL,
    excel_row INTEGER NOT NULL,
    dataframe_index INTEGER NOT NULL,
    source_order INTEGER NOT NULL,
    PRIMARY KEY (snapshot_fingerprint, excel_row)
);
CREATE TABLE import_issues (
    snapshot_fingerprint VARCHAR NOT NULL,
    issue_order INTEGER NOT NULL,
    excel_row INTEGER NOT NULL,
    field VARCHAR NOT NULL,
    code VARCHAR NOT NULL,
    message VARCHAR NOT NULL,
    PRIMARY KEY (snapshot_fingerprint, issue_order)
);
CREATE TABLE cells (
    snapshot_fingerprint VARCHAR NOT NULL,
    excel_row INTEGER NOT NULL,
    position SMALLINT NOT NULL,
    field VARCHAR NOT NULL,
    raw_type VARCHAR NOT NULL,
    value_text VARCHAR,
    value_integer BIGINT,
    value_number DOUBLE,
    value_boolean BOOLEAN,
    value_timestamp TIMESTAMP,
    number_format VARCHAR,
    PRIMARY KEY (snapshot_fingerprint, excel_row, position)
);
"""

TICKET_COLUMNS = {
    "snapshot_fingerprint": "VARCHAR",
    "excel_row": "INTEGER",
    "dataframe_index": "INTEGER",
    "source_order": "INTEGER",
}

ISSUE_COLUMNS = {
    "snapshot_fingerprint": "VARCHAR",
    "issue_order": "INTEGER",
    "excel_row": "INTEGER",
    "field": "VARCHAR",
    "code": "VARCHAR",
    "message": "VARCHAR",
}

CELL_COLUMNS = {
    "snapshot_fingerprint": "VARCHAR",
    "excel_row": "INTEGER",
    "position": "SMALLINT",
    "field": "VARCHAR",
    "raw_type": "VARCHAR",
    "value_text": "VARCHAR",
    "value_integer": "BIGINT",
    "value_number": "DOUBLE",
    "value_boolean": "BOOLEAN",
    "value_timestamp": "TIMESTAMP",
    "number_format": "VARCHAR",
}


class SnapshotStore:
    """Snapshot tables keyed by fingerprint; one workbook content is one Snapshot.

    Request handlers run on worker threads and a DuckDB connection is not safe
    to share between them, so every public method holds the store's lock.
    """

    def __init__(self, connection: duckdb.DuckDBPyConnection | None = None) -> None:
        self.connection = connection or duckdb.connect(database=":memory:")
        self.connection.execute(SCHEMA)
        self._lock = threading.RLock()

    def has_snapshot(self, fingerprint: str) -> bool:
        with self._lock:
            return self.connection.execute(
                "SELECT count(*) FROM snapshots WHERE fingerprint = ?", [fingerprint]
            ).fetchone()[0] > 0

    def add_snapshot(self, snapshot: Snapshot) -> bool:
        """Store a Snapshot; a fingerprint already stored is left untouched.

        Returns whether anything was added, so reimporting identical content
        is a no-op that keeps the original import time and Tickets.
        """
        with self._lock:
            if self.has_snapshot(snapshot.fingerprint):
                return False
            self.connection.execute("BEGIN TRANSACTION")
            try:
                self._insert(snapshot)
            except BaseException:
                self.connection.execute("ROLLBACK")
                raise
            self.connection.execute("COMMIT")
            return True

    def snapshots(self) -> list[dict[str, Any]]:
        """Every stored Snapshot in import order."""
        with self._lock:
            rows = self.connection.execute(
                "SELECT fingerprint, workbook_name, sheet, row_count, imported_at FROM snapshots"
                " ORDER BY imported_at, fingerprint"
            ).fetchall()
        return [
            {"fingerprint": row[0], "workbook_name": row[1], "sheet": row[2], "row_count": row[3], "imported_at": row[4]}
            for row in rows
        ]

    def _insert(self, snapshot: Snapshot) -> None:
        self.connection.execute(
            "INSERT INTO snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                snapshot.fingerprint,
                snapshot.fingerprint_algorithm,
                snapshot.workbook_name,
                snapshot.sheet,
                snapshot.row_count,
                snapshot.field_count,
                list(snapshot.fields),
                snapshot.imported_at.isoformat(),
                snapshot.missing_optional_columns,
                json.dumps(snapshot.disabled_features),
            ],
        )
        self._bulk_insert(
            "tickets",
            TICKET_COLUMNS,
            (
                (snapshot.fingerprint, ticket.excel_row, ticket.dataframe_index, order)
                for order, ticket in enumerate(snapshot.tickets)
            ),
        )
        self._bulk_insert(
            "import_issues",
            ISSUE_COLUMNS,
            (
                (snapshot.fingerprint, order, issue["excel_row"], issue["field"], issue["code"], issue["message"])
                for order, issue in enumerate(snapshot.import_issues)
            ),
        )
        self._bulk_insert(
            "cells",
            CELL_COLUMNS,
            (
                _cell_row(snapshot.fingerprint, ticket.excel_row, cell)
                for ticket in snapshot.tickets
                for cell in ticket.cells
            ),
        )

    def _bulk_insert(self, table: str, columns: dict[str, str], rows: Iterable[tuple[Any, ...]]) -> None:
        """Load rows through a short-lived newline-delimited JSON file.

        Binding parameters row by row costs milliseconds per row in DuckDB;
        its JSON reader loads the same rows in a fraction of a second. The
        file is deleted as soon as the load finishes.
        """
        names = list(columns)
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as handle:
            path = handle.name
            for row in rows:
                handle.write(json.dumps(dict(zip(names, row)), default=_json_default))
                handle.write("\n")
        try:
            column_list = ", ".join(names)
            self.connection.execute(
                f"INSERT INTO {table} ({column_list}) SELECT {column_list}"
                " FROM read_json(?, format = 'newline_delimited', columns = ?)",
                [path, columns],
            )
        finally:
            os.unlink(path)

    def snapshot_header(self, fingerprint: str) -> dict[str, Any] | None:
        with self._lock:
            return self._snapshot_header(fingerprint)

    def _snapshot_header(self, fingerprint: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT fingerprint, fingerprint_algorithm, workbook_name, sheet, row_count, field_count,"
            " fields, imported_at, missing_optional_columns, disabled_features"
            " FROM snapshots WHERE fingerprint = ?",
            [fingerprint],
        ).fetchone()
        if row is None:
            return None
        issues = self._issues(fingerprint)
        return {
            "fingerprint": row[0],
            "fingerprint_algorithm": row[1],
            "workbook_name": row[2],
            "sheet": row[3],
            "row_count": row[4],
            "field_count": row[5],
            "fields": list(row[6]),
            "imported_at": row[7],
            "import_issue_count": len(issues),
            "import_issues": issues,
            "missing_optional_columns": list(row[8]),
            "disabled_features": json.loads(row[9]),
        }

    def _issues(self, fingerprint: str, excel_row: int | None = None) -> list[dict[str, Any]]:
        query = "SELECT excel_row, field, code, message FROM import_issues WHERE snapshot_fingerprint = ?"
        parameters: list[Any] = [fingerprint]
        if excel_row is not None:
            query += " AND excel_row = ?"
            parameters.append(excel_row)
        rows = self.connection.execute(query + " ORDER BY issue_order", parameters).fetchall()
        return [
            {"excel_row": row[0], "field": row[1], "code": row[2], "message": row[3]}
            for row in rows
        ]

    def ticket(self, fingerprint: str, excel_row: int) -> dict[str, Any] | None:
        with self._lock:
            return self._ticket(fingerprint, excel_row)

    def _ticket(self, fingerprint: str, excel_row: int) -> dict[str, Any] | None:
        provenance = self.connection.execute(
            "SELECT t.dataframe_index, s.sheet FROM tickets t JOIN snapshots s"
            " ON s.fingerprint = t.snapshot_fingerprint"
            " WHERE t.snapshot_fingerprint = ? AND t.excel_row = ?",
            [fingerprint, excel_row],
        ).fetchone()
        if provenance is None:
            return None
        rows = self.connection.execute(
            "SELECT field, position, raw_type, value_text, value_integer, value_number,"
            " value_boolean, value_timestamp, number_format FROM cells"
            " WHERE snapshot_fingerprint = ? AND excel_row = ? ORDER BY position",
            [fingerprint, excel_row],
        ).fetchall()
        return {
            "snapshot_fingerprint": fingerprint,
            "sheet": provenance[1],
            "excel_row": excel_row,
            "dataframe_index": provenance[0],
            "cells": [_cell_payload(row) for row in rows],
            "issues": self._issues(fingerprint, excel_row),
        }


# Which storage column holds a cell's value, by raw type. Types not listed
# (str, formula, error, date, time, duration) are kept as text; "blank" has no value.
VALUE_COLUMN_BY_RAW_TYPE = {
    "bool": "value_boolean",
    "int": "value_integer",
    "float": "value_number",
    "datetime": "value_timestamp",
}
VALUE_COLUMNS = ("value_text", "value_integer", "value_number", "value_boolean", "value_timestamp")


def _value_column(raw_type: str) -> str | None:
    if raw_type == "blank":
        return None
    return VALUE_COLUMN_BY_RAW_TYPE.get(raw_type, "value_text")


def _cell_row(fingerprint: str, excel_row: int, cell: Cell) -> tuple[Any, ...]:
    values: dict[str, Any] = dict.fromkeys(VALUE_COLUMNS)
    column = _value_column(cell.raw_type)
    if column == "value_text" and cell.raw_type in ("date", "time", "duration"):
        values[column] = cell.value.isoformat() if hasattr(cell.value, "isoformat") else str(cell.value)
    elif column is not None:
        values[column] = cell.value
    return (
        fingerprint,
        excel_row,
        cell.position,
        cell.field,
        cell.raw_type,
        *(values[name] for name in VALUE_COLUMNS),
        cell.number_format,
    )


def _json_default(value: Any) -> str:
    if isinstance(value, dt.datetime):
        return value.isoformat(sep=" ")
    raise TypeError(f"cannot serialise {type(value).__name__} for bulk insert")


def _cell_payload(row: tuple[Any, ...]) -> dict[str, Any]:
    field_name, position, raw_type, *stored, number_format = row
    values = dict(zip(VALUE_COLUMNS, stored))
    column = _value_column(raw_type)
    value = values[column] if column is not None else None
    if isinstance(value, dt.datetime):
        value = value.isoformat()
    return {
        "field": field_name,
        "position": position,
        "raw_type": raw_type,
        "value": value,
        "number_format": number_format,
    }
