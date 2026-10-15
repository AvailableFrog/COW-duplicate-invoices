"""DuckDB tables for Snapshots.

Snapshot tables are rebuilt from the workbook on every launch and hold the
source Tickets as cells with raw value, raw type, Excel row and dataframe
index. Each Ticket's Time cell is also parsed once at import and the parse
results are kept beside the tables, keyed by Excel row. The matching rules run
at import too and their Candidates are stored as relationship edges, apart
from the Tickets; Possible Duplicates are recomposed from them on every read.
Local review data lives in a separate file (review.py) and is never mixed
into these tables.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import threading
from typing import Any, Iterable

import duckdb

from labour_ticket_analytics import evidence, metrics, normalized, rules
from labour_ticket_analytics.annotations import ANNOTATIONS
from labour_ticket_analytics.filters import DATE_BASES, Filters
from labour_ticket_analytics.timeparse import TimeParse, parse_time
from labour_ticket_analytics.validation import APPROVAL_STATUSES
from labour_ticket_analytics.workbook import Cell, Snapshot, Ticket

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
    field VARCHAR,
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
CREATE TABLE candidates (
    snapshot_fingerprint VARCHAR NOT NULL,
    rule_id VARCHAR NOT NULL,
    first_row INTEGER NOT NULL,
    second_row INTEGER NOT NULL,
    fields_compared VARCHAR[] NOT NULL,
    evidence_strength VARCHAR NOT NULL,
    reason VARCHAR NOT NULL,
    pattern VARCHAR NOT NULL,
    PRIMARY KEY (snapshot_fingerprint, rule_id, first_row, second_row)
);
"""

# Normalized values beside the raw cells: what metrics and filters read.
SCHEMA += (
    "CREATE TABLE ticket_values ("
    + ", ".join(f"{name} {kind}" for name, kind in normalized.COLUMNS.items())
    + ", PRIMARY KEY (snapshot_fingerprint, excel_row));"
)

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
        self._time_parses: dict[str, dict[int, TimeParse]] = {}

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
            time_parses = {ticket.excel_row: _parse_ticket_time(ticket) for ticket in snapshot.tickets}
            self.connection.execute("BEGIN TRANSACTION")
            try:
                self._insert(snapshot)
                rules.record_candidates(self.connection, snapshot.fingerprint, time_parses)
            except BaseException:
                self.connection.execute("ROLLBACK")
                raise
            self.connection.execute("COMMIT")
            self._time_parses[snapshot.fingerprint] = time_parses
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
        self._bulk_insert(
            "ticket_values",
            normalized.COLUMNS,
            (normalized.ticket_values(snapshot.fingerprint, ticket) for ticket in snapshot.tickets),
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

    def fields(self, fingerprint: str) -> tuple[str, ...]:
        with self._lock:
            row = self.connection.execute("SELECT fields FROM snapshots WHERE fingerprint = ?", [fingerprint]).fetchone()
        return tuple(row[0]) if row else ()

    def evaluate_metric(
        self,
        fingerprint: str,
        metric: metrics.Metric,
        filters: Filters,
        as_of: dt.date,
        group_by: str | None = None,
        include_rows: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            return metrics.evaluate(
                self.connection, fingerprint, self.fields(fingerprint), metric, filters, as_of, group_by, include_rows
            )

    def filter_options(self, fingerprint: str) -> dict[str, Any]:
        """What the filter bar can offer for a Snapshot: date bases with their spans, statuses and jobs."""
        with self._lock:
            fields = self.fields(fingerprint)
            spans = self.connection.execute(
                "SELECT " + ", ".join(
                    f"CAST(min({column}) AS DATE), CAST(max({column}) AS DATE)" for column, _ in DATE_BASES.values()
                ) + " FROM ticket_values WHERE snapshot_fingerprint = ?",
                [fingerprint],
            ).fetchone()
            statuses = dict(self.connection.execute(
                "SELECT status, count(*) FROM ticket_values WHERE snapshot_fingerprint = ? AND status IS NOT NULL"
                " GROUP BY status",
                [fingerprint],
            ).fetchall())
            jobs = self.connection.execute(
                "SELECT job_number, mode(job_name), count(*) FROM ticket_values"
                " WHERE snapshot_fingerprint = ? AND job_number IS NOT NULL GROUP BY job_number ORDER BY job_number",
                [fingerprint],
            ).fetchall()
        return {
            "date_bases": [
                {
                    "id": basis,
                    "label": label,
                    "available": basis in fields,
                    "earliest": _iso(spans[2 * index]),
                    "latest": _iso(spans[2 * index + 1]),
                }
                for index, (basis, (_, label)) in enumerate(DATE_BASES.items())
            ],
            "statuses": [{"id": status, "tickets": statuses.get(status, 0)} for status in APPROVAL_STATUSES],
            "jobs": [{"job_number": job, "job_name": name, "tickets": count} for job, name, count in jobs],
        }

    def possible_duplicates(self, fingerprint: str, filters: Filters) -> list[dict[str, Any]]:
        """The Possible Duplicates with any member inside the filters, recomposed from Candidates and ranked.

        Every member stays listed, marked in or out of the filters, so a
        comparison is never truncated.
        """
        with self._lock:
            candidates = self._candidates(fingerprint)
            members = self._candidate_members(fingerprint, filters)
        composed = [rules.possible_duplicate(component, members) for component in rules.compose(candidates)]
        return rules.ranked([item for item in composed if any(member["in_filter"] for member in item["members"])])

    def possible_duplicate_evidence(self, fingerprint: str, excel_row: int, filters: Filters) -> dict[str, Any] | None:
        """The evidence for the Possible Duplicate holding a Ticket, or None when the Ticket is in none.

        Possible Duplicates are disjoint, so any member Ticket names exactly
        one; it is recomposed from the Candidates like the list, and every
        member is shown whether or not it is inside the filters.
        """
        with self._lock:
            component = next(
                (
                    component for component in rules.compose(self._candidates(fingerprint))
                    if any(excel_row in (candidate.first_row, candidate.second_row) for candidate in component)
                ),
                None,
            )
            if component is None:
                return None
            item = rules.possible_duplicate(component, self._candidate_members(fingerprint, filters))
            tickets = [self._ticket(fingerprint, member["excel_row"]) for member in item["members"]]
            parses = {member["excel_row"]: self._time_parses[fingerprint][member["excel_row"]] for member in item["members"]}
        return evidence.evidence(item, tickets, parses, ANNOTATIONS)

    def pair_explanation(
        self, fingerprint: str, first_row: int, second_row: int, filters: Filters
    ) -> dict[str, Any] | None:
        """Why two Tickets are or are not linked, with their evidence; None when either Ticket is unknown.

        Every rule gives its verdict, so a pair with no Candidate (such as two
        separate work periods) is explained as well as a linked one.
        """
        rows = sorted((first_row, second_row))
        with self._lock:
            parses = self._time_parses.get(fingerprint)
            if parses is None or any(row not in parses for row in rows):
                return None
            facts = rules.pair_tickets(self.connection, fingerprint, parses, rows)
            members = self._members(fingerprint, filters, "list_contains($rows, t.excel_row)", {"rows": rows})
            tickets = [self._ticket(fingerprint, row) for row in rows]
            # The possible duplicate each Ticket is in, by display name; a Ticket in none has no entry.
            linked = self._candidate_members(fingerprint, filters)
            display_ids: dict[int, str] = {}
            for component in rules.compose(self._candidates(fingerprint)):
                component_rows = {row for candidate in component for row in (candidate.first_row, candidate.second_row)}
                if component_rows & set(rows):
                    name = rules.display_id([linked[row] for row in component_rows])
                    display_ids.update(dict.fromkeys(component_rows & set(rows), name))
        explanation = rules.explain(facts[rows[0]], facts[rows[1]])
        return evidence.pair_explanation(
            explanation, [members[row] for row in rows], tickets, parses, display_ids, ANNOTATIONS
        )

    def excel_rows_by_ticket_number(self, fingerprint: str, ticket_numbers: Iterable[str]) -> dict[str, int]:
        """Where each ticket number sits in a Snapshot, compared as written; the first row if it repeats."""
        with self._lock:
            rows = self.connection.execute(
                "SELECT ticket_number, min(excel_row) FROM ticket_values"
                " WHERE snapshot_fingerprint = ? AND list_contains(?, ticket_number) GROUP BY ticket_number",
                [fingerprint, list(ticket_numbers)],
            ).fetchall()
        return dict(rows)

    def ticket_numbers(self, fingerprint: str, excel_rows: Iterable[int]) -> dict[int, str | None]:
        """Each Ticket's ticket number as written, by Excel row; None where it is blank."""
        with self._lock:
            rows = self.connection.execute(
                "SELECT excel_row, ticket_number FROM ticket_values"
                " WHERE snapshot_fingerprint = ? AND list_contains(?, excel_row)",
                [fingerprint, list(excel_rows)],
            ).fetchall()
        return dict(rows)

    def candidate_rule_ids(self, fingerprint: str, first_row: int, second_row: int) -> list[str]:
        """The rules with a Candidate linking two Tickets, in either order; empty when none does."""
        with self._lock:
            return sorted(
                candidate.rule_id for candidate in self._candidates(fingerprint)
                if {candidate.first_row, candidate.second_row} == {first_row, second_row}
            )

    def possible_duplicate_rows(self, fingerprint: str, excel_row: int) -> set[int]:
        """The member Excel rows of the Possible Duplicate holding a Ticket; empty when it is in none."""
        with self._lock:
            for component in rules.compose(self._candidates(fingerprint)):
                rows = {row for candidate in component for row in (candidate.first_row, candidate.second_row)}
                if excel_row in rows:
                    return rows
        return set()

    def _candidates(self, fingerprint: str) -> list[rules.Candidate]:
        return [
            rules.Candidate(row[0], row[1], row[2], tuple(row[3]), row[4], row[5], row[6])
            for row in self.connection.execute(
                "SELECT rule_id, first_row, second_row, fields_compared, evidence_strength, reason, pattern"
                " FROM candidates WHERE snapshot_fingerprint = ?",
                [fingerprint],
            ).fetchall()
        ]

    def _candidate_members(self, fingerprint: str, filters: Filters) -> dict[int, dict[str, Any]]:
        """Each Ticket in a Candidate with its source state and whether it is inside the filters."""
        return self._members(fingerprint, filters, rules.IN_CANDIDATE_SQL)

    def _members(
        self, fingerprint: str, filters: Filters, scope_sql: str, scope_parameters: dict[str, Any] | None = None
    ) -> dict[int, dict[str, Any]]:
        """Tickets matching `scope_sql` (over ticket_values `t`) with their source state and filter membership."""
        filter_sql, parameters = filters.sql("t")
        rows = self.connection.execute(
            "SELECT t.excel_row, t.ticket_number, t.employee_name, t.work_date, t.job_number, t.status, t.keyed,"
            f" COALESCE({metrics.FLAGGED_DUPLICATE_SCOPE}, false), t.created, COALESCE({filter_sql}, false)"
            f" FROM ticket_values t WHERE t.snapshot_fingerprint = $fingerprint AND {scope_sql}",
            {**parameters, **(scope_parameters or {}), "fingerprint": fingerprint},
        ).fetchall()
        return {
            row[0]: {
                "excel_row": row[0],
                "ticket_number": row[1],
                "employee": row[2],
                "date": _iso(row[3].date()) if row[3] is not None else None,
                "job_number": row[4],
                "status": row[5],
                "keyed": row[6],
                "flagged_duplicate": row[7],
                "created": _iso(row[8]),
                "in_filter": row[9],
            }
            for row in rows
        }

    def time_parse(self, fingerprint: str, excel_row: int) -> TimeParse | None:
        """A Ticket's Time cell as the interval parser read it at import."""
        with self._lock:
            return self._time_parses.get(fingerprint, {}).get(excel_row)

    def time_parse_summary(self, fingerprint: str) -> list[dict[str, Any]] | None:
        """How every Time cell in a Snapshot parsed: Tickets and Excel rows by status and raw type."""
        with self._lock:
            parses = self._time_parses.get(fingerprint)
        if parses is None:
            return None
        groups: dict[tuple[str, str], list[int]] = {}
        for excel_row, parse in parses.items():
            groups.setdefault((parse.status, parse.raw_type), []).append(excel_row)
        return [
            {"status": status, "raw_type": raw_type, "tickets": len(rows), "excel_rows": sorted(rows)}
            for (status, raw_type), rows in sorted(groups.items())
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


def _parse_ticket_time(ticket: Ticket) -> TimeParse:
    time = next(cell for cell in ticket.cells if cell.field == "Time")
    return parse_time(time.raw_type, time.value)


def _iso(value: dt.date | None) -> str | None:
    return value.isoformat() if value is not None else None


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
