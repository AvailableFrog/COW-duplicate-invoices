"""CSV exports of an Explore table or drilldown, protected from spreadsheet formula injection.

`table_rows` and `drilldown_csv_rows` lay out an executed plan's table and a
drilldown as rows; `csv_text` writes them.

A cell whose text begins with "=", "+", "-", "@", a tab or a carriage return
could run as a formula when the file is opened in a spreadsheet, so it is
written with a leading single quote, and every cell is quoted (the OWASP
CSV-injection guidance). Only the file is changed: the stored source value
and every API response keep the raw text. Numbers the application computed
are written as numbers. Each row carries the Snapshot, as-of date and
registry version, so a file read on its own still names where it came from.
"""

from __future__ import annotations

import csv
import io
from typing import Any

from labour_ticket_analytics import plans
from labour_ticket_analytics.filters import DATE_BASES

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
PROVENANCE_COLUMNS = ("Snapshot", "As of", "Registry version")


def protect(value: Any) -> str:
    """One cell as written to the file: text that could start a formula gains a leading quote."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return f"'{value}" if value.startswith(FORMULA_PREFIXES) else value
    return str(value)


def csv_text(header: list[str], rows: list[list[Any]], provenance: tuple[str, str, str]) -> str:
    """The rows as UTF-8 CSV text (with a byte-order mark for spreadsheets), every cell protected and quoted."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writerow([protect(item) for item in (*header, *PROVENANCE_COLUMNS)])
    for row in rows:
        writer.writerow([protect(item) for item in (*row, *provenance)])
    return "\ufeff" + buffer.getvalue()


def table_rows(executed: plans.Executed) -> tuple[list[str], list[list[Any]]]:
    """The result table as CSV rows: every group (or bin, or point) with Other and the total below."""
    payload = executed.payload
    block = payload["result"]
    form = block["form"]
    if form == "pair":
        header = ["Excel row", plans.value_title(payload), f"{payload['paired_metric']['label']} ({payload['paired_metric']['unit']})"]
        return header, [[point["excel_row"], point["x"], point["y"]] for point in block["points"] or []]
    plan = payload["plan"]
    dimension = plan["group_by"][0] if plan["group_by"] else "Plan"
    if form == "dates":
        dimension = f"{dimension} of {DATE_BASES[plan['date_basis']][1]}"
    elif form == "distribution":
        dimension = f"{payload['metric']['label']} ({payload['metric']['unit']})"
    counted = payload["metric"]["statistic"] == "sum"
    header = [dimension, block["value_title"], *(["Tickets"] if counted else []), "In the chart"]
    rows = []
    for group in block["groups"]:
        where = "Own bar" if group["shown"] else "In Other" if group["in_other"] else "Not drawn"
        rows.append([group["label"], group["value"], *([group["contributing_tickets"]] if counted else []), where])
    if block["other"]:
        other = block["other"]
        rows.append([other["label"], other["value"], *([other["contributing_tickets"]] if counted else []), "Bar for the rows In Other"])
    rows.append(["Total", block["total"], *([block["contributing_tickets"]] if counted else []), ""])
    return header, rows


DRILLDOWN_COLUMNS = (
    ("excel_row", "Excel row"), ("ticket_number", "Ticket Number"), ("employee", "Employee"), ("date", "Date"),
    ("created", "Created"), ("date_approved", "Date Approved"), ("status", "Approval Status"), ("keyed", "Keyed"),
    ("job_number", "Job Number"), ("job_name", "Job Name"), ("supervisor", "Supervisor"),
    ("occupation", "Occupation"), ("description", "Description of Job Work"),
)


def drilldown_csv_rows(listing: dict[str, Any]) -> tuple[list[str], list[list[Any]]]:
    """The drilldown as CSV rows: each Ticket's fields as recorded and its value."""
    header = [label for _, label in DRILLDOWN_COLUMNS]
    extra = [key for key in ("value_title", "paired_value_title") if listing[key]]
    header += [listing[key] for key in extra]
    rows = []
    for row in listing["rows"]:
        values = [row[key] for key, _ in DRILLDOWN_COLUMNS]
        values += [row["value"] if key == "value_title" else row["paired_value"] for key in extra]
        rows.append(values)
    return header, rows
