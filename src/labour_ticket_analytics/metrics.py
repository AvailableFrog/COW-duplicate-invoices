"""The metric registry: every number the application returns resolves through it.

Each metric is declared once with the attributes PRD section 4 requires (ID,
label, definition, unit, grain, allowed dimensions, null treatment, date
basis, exclusions and source-row lineage) and with the SQL that computes it
over normalized Ticket values. Changing any definition or its SQL means
bumping REGISTRY_VERSION, because every response carries it.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

import duckdb

from labour_ticket_analytics.filters import DATE_BASES, Filters
from labour_ticket_analytics.rules import IN_CANDIDATE_SQL, STRICT_KEY, strict_groups_sql

REGISTRY_VERSION = "1.3.0"

# Grouping dimension ID (the source column) -> normalized column.
DIMENSIONS = {
    "Approval Status": "status",
    "Keyed": "keyed",
    "Job Number": "job_number",
    "Job Name": "job_name",
    "Supervisor": "supervisor",
    "Occupation": "occupation",
}
TICKET_DIMENSIONS = tuple(DIMENSIONS)

CLAIMED_HOURS_SQL = "(t.regular_hours + t.overtime + t.double_time)"
HOURS_UNUSABLE_SQL = "(t.regular_hours IS NULL OR t.overtime IS NULL OR t.double_time IS NULL)"
# Recorded Rate x claimed hours, kept in exact decimals so per-Ticket rounding is half-up to cents.
LABOUR_VALUE_SQL = (
    "CAST(t.rate AS DECIMAL(18, 4)) * (CAST(t.regular_hours AS DECIMAL(18, 4))"
    " + CAST(t.overtime AS DECIMAL(18, 4)) + CAST(t.double_time AS DECIMAL(18, 4)))"
)
# Labour is known when every hour component is usable and either a Rate is recorded or no hours are claimed.
LABOUR_KNOWN_SQL = f"(NOT {HOURS_UNUSABLE_SQL} AND (t.rate IS NOT NULL OR {CLAIMED_HOURS_SQL} = 0))"
# The hours left unpriced: every usable component, so an invalid one does not hide the others.
USABLE_HOURS_SQL = "(COALESCE(t.regular_hours, 0) + COALESCE(t.overtime, 0) + COALESCE(t.double_time, 0))"

Aggregation = Literal["count", "count_distinct", "sum", "distribution", "possible_duplicate_count"]
# The statistic each aggregation reports as a metric's value.
STATISTICS: dict[str, str] = {
    "count": "count", "count_distinct": "distinct count", "sum": "sum", "distribution": "median", "possible_duplicate_count": "count",
}


@dataclass(frozen=True)
class Exclusion:
    """Tickets in a metric's scope left out of its value, each for a stated reason."""

    code: str
    predicate: str
    message: str


@dataclass(frozen=True)
class Partial:
    """Tickets that contribute only some of their components; quantity measures what is missing."""

    code: str
    predicate: str
    message: str
    quantity: str | None = None
    quantity_unit: str | None = None


@dataclass(frozen=True)
class Bucket:
    """One range of a whole-number distribution's values, both ends inclusive; no `max` means open-ended."""

    id: str
    label: str
    min: int
    max: int | None = None

    def predicate(self, column: str = "metric_value") -> str:
        upper = f" AND {column} <= {self.max}" if self.max is not None else ""
        return f"({column} >= {self.min}{upper})"

    def payload(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label, "min": self.min, "max": self.max}


def _contiguous(buckets: tuple[Bucket, ...]) -> tuple[Bucket, ...]:
    """Buckets that cover every whole value from the first minimum upward, once each, ending open."""
    for before, after in zip(buckets, buckets[1:]):
        if before.max is None or after.min != before.max + 1:
            raise ValueError(f"bucket {after.id!r} does not follow {before.id!r}")
    if buckets and buckets[-1].max is not None:
        raise ValueError("the last bucket must be open-ended")
    return buckets


# Age since submission in whole days, as of the analytical date (decision-log entry 57). Day by day through
# the first half-week, where most of the export's queue sits, then the rest of the week, the second week,
# the rest of the month and anything older; fixed edges, so a later as-of date moves Tickets between
# buckets rather than redrawing them.
AGE_BUCKETS = _contiguous((
    Bucket("0", "0 days", 0, 0),
    Bucket("1", "1 day", 1, 1),
    Bucket("2", "2 days", 2, 2),
    Bucket("3", "3 days", 3, 3),
    Bucket("4-6", "4–6 days", 4, 6),
    Bucket("7-13", "7–13 days", 7, 13),
    Bucket("14-29", "14–29 days", 14, 29),
    Bucket("30-or-more", "30 days or more", 30),
))


@dataclass(frozen=True)
class Metric:
    id: str
    label: str
    definition: str
    unit: str
    grain: str
    aggregation: Aggregation
    null_treatment: str
    lineage: str
    exclusions_text: tuple[str, ...] = ()
    allowed_dimensions: tuple[str, ...] = TICKET_DIMENSIONS
    measured_on: str | None = None
    scope: str = "TRUE"
    value: str | None = None
    exclusions: tuple[Exclusion, ...] = ()
    partials: tuple[Partial, ...] = ()
    share_of: str | None = None
    requires_columns: tuple[str, ...] = ()
    # Value ranges a distribution can be counted by; each bucket's Tickets are listed by bucket_rows.
    buckets: tuple[Bucket, ...] = ()

    @property
    def statistic(self) -> str:
        return STATISTICS[self.aggregation]

    def availability(self, fields: tuple[str, ...] | list[str]) -> dict[str, str | None]:
        missing = [column for column in self.requires_columns if column not in fields]
        if missing:
            return {
                "status": "disabled",
                "reason": f"The workbook has no {', '.join(missing)} column, so this metric cannot be computed.",
            }
        return {"status": "available", "reason": None}

    def payload(self, fields: tuple[str, ...] | list[str]) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "definition": self.definition,
            "unit": self.unit,
            "grain": self.grain,
            "statistic": self.statistic,
            "allowed_dimensions": list(self.allowed_dimensions),
            "null_treatment": self.null_treatment,
            "date_basis": {
                "filter_bases": [{"id": key, "label": label} for key, (_, label) in DATE_BASES.items()],
                "default_range": "all dates",
                "measured_on": self.measured_on,
                "note": "Totals cover all dates unless a date range is set; a range always names its date basis.",
            },
            "exclusions": list(self.exclusions_text),
            "lineage": self.lineage,
            "percentage_of": self.share_of,
            "requires_columns": list(self.requires_columns),
            "buckets": [bucket.payload() for bucket in self.buckets],
            "availability": self.availability(fields),
        }


def _age_metric(metric_id: str, label: str, population: str, scope: str) -> Metric:
    return Metric(
        id=metric_id,
        label=label,
        definition=(
            f"The as-of date minus the calendar date of Created, in whole days, for {population}. "
            "This is age since submission, not time spent waiting in the current state."
        ),
        unit="days",
        grain="Ticket",
        aggregation="distribution",
        null_treatment="A Ticket with an unusable Created date is excluded and counted, never aged from zero.",
        exclusions_text=(
            "Created is missing or not a date",
            "Created falls after the as-of date: such a Ticket is left out and reported, never aged as zero",
        ),
        lineage=f"One value per {population.removeprefix('currently ')} Ticket, from its Created cell and the as-of date.",
        measured_on="Created to the analytical as-of date",
        scope=scope,
        value="date_diff('day', CAST(t.created AS DATE), $as_of)",
        exclusions=(
            Exclusion("created_unusable", "t.created IS NULL", "Created is missing or not a date"),
            Exclusion("created_after_as_of", "CAST(t.created AS DATE) > $as_of", "Created falls after the as-of date"),
        ),
        buckets=AGE_BUCKETS,
    )


FLAGGED_DUPLICATE_SCOPE = "t.status = 'Approved' AND t.job_number = 0"
PENDING_SCOPE = "t.status = 'Pending'"
APPROVED_NOT_KEYED_SCOPE = "t.status = 'Approved' AND t.keyed = false"

REGISTRY: tuple[Metric, ...] = (
    Metric(
        id="ticket_count",
        label="Source records",
        definition="Number of Tickets in the active Snapshot under the active filters. Every source row counts once, including rows with import issues; unique IDs are validated at import rather than assumed.",
        unit="tickets",
        grain="Ticket",
        aggregation="count",
        null_treatment="Every Ticket counts, whatever its cells hold.",
        lineage="One per Excel row of the data sheet in the active Snapshot.",
        value="1",
    ),
    Metric(
        id="flagged_duplicate_count",
        label="Flagged duplicates",
        definition=(
            "Tickets staff flagged as duplicates by approving them with Job Number 0: Approval Status is Approved "
            "and Job Number is the number 0. Oliver described these as “more than likely a duplicate”; the flag "
            "is a fact about what staff did, and the count asserts nothing about whether the analysis agrees or "
            "about payment. It counts Tickets, not Confirmed Duplicates."
        ),
        unit="tickets",
        grain="Ticket",
        aggregation="count",
        null_treatment="An invalid Approval Status or a Job Number that is not a whole number never matches.",
        exclusions_text=("Tickets with any other status or job",),
        lineage="Each Approved Ticket whose Job Number cell holds 0.",
        scope=FLAGGED_DUPLICATE_SCOPE,
        value="1",
        share_of="ticket_count",
    ),
    Metric(
        id="unflagged_exact_repeat_count",
        label="Exact repeats, not flagged",
        definition=(
            "Possible duplicates found by the Strict repeat rule (normalized Employee, Date as recorded, Job Number, "
            "normalized Time and all four hour and pay amounts match) in which no Ticket is a flagged duplicate "
            "and every Ticket is Approved and Keyed. "
            "Counts possible duplicates, not Tickets; whether staff handled them somewhere the export cannot show "
            "is a question for Oliver, so they are not called missed."
        ),
        unit="possible duplicates",
        grain="Possible duplicate",
        aggregation="possible_duplicate_count",
        null_treatment="A missing or invalid comparison field never satisfies equality, so that Ticket is never in a group.",
        exclusions_text=(
            "Possible duplicates holding a flagged duplicate",
            "Possible duplicates with any Ticket not Approved and Keyed",
            "Tickets with a missing or invalid comparison field, which are reported",
        ),
        lineage="Each possible duplicate lists its member Tickets by Excel row.",
        allowed_dimensions=(),
    ),
    Metric(
        id="candidate_ticket_count",
        label="Candidate Tickets",
        definition="Distinct Tickets taking part in at least one Candidate from the matching rules built so far; Tickets are unioned before counting.",
        unit="tickets",
        grain="Ticket",
        aggregation="count",
        null_treatment="A Ticket counts once however many rules or Candidates it appears in.",
        lineage="Each Candidate names its two Tickets by Excel row.",
        scope=IN_CANDIDATE_SQL,
        value="1",
        share_of="ticket_count",
    ),
    Metric(
        id="pending_count",
        label="Pending",
        definition="Tickets whose Approval Status is Pending, whatever their Keyed value. Pending does not prove that nobody reviewed a Ticket or that a warning caught it.",
        unit="tickets",
        grain="Ticket",
        aggregation="count",
        null_treatment="An invalid Approval Status never matches.",
        exclusions_text=("Approved and Rejected Tickets",),
        lineage="Each Ticket whose Approval Status cell is Pending.",
        scope=PENDING_SCOPE,
        value="1",
        share_of="ticket_count",
    ),
    Metric(
        id="approved_not_keyed_count",
        label="Approved, not Keyed",
        definition="Tickets whose Approval Status is Approved and whose Keyed cell is false.",
        unit="tickets",
        grain="Ticket",
        aggregation="count",
        null_treatment="A Keyed cell that is not true or false is a separate import issue and never counts as false.",
        exclusions_text=("Tickets that are not Approved", "Approved Tickets with Keyed true or unknown"),
        lineage="Each Approved Ticket whose Keyed cell is false.",
        scope=APPROVED_NOT_KEYED_SCOPE,
        value="1",
        share_of="ticket_count",
    ),
    _age_metric("pending_submission_age_days", "Pending: age since submission", "currently Pending Tickets", PENDING_SCOPE),
    _age_metric(
        "approved_not_keyed_submission_age_days",
        "Approved, not Keyed: age since submission",
        "currently Approved, not Keyed Tickets",
        APPROVED_NOT_KEYED_SCOPE,
    ),
    Metric(
        id="claimed_hours",
        label="Claimed hours",
        definition="Regular Hours + Overtime + Double Time as recorded, with no pay multipliers. Repeated claims are included as recorded.",
        unit="hours",
        grain="Ticket",
        aggregation="sum",
        null_treatment="A Ticket with a missing or invalid hour component is left out and reported in a coverage warning, never counted as zero.",
        exclusions_text=("Tickets with a missing or invalid Regular Hours, Overtime or Double Time cell",),
        lineage="Each contributing Ticket's three hour cells.",
        value=f"CAST({CLAIMED_HOURS_SQL} AS DECIMAL(18, 4))",
        exclusions=(
            Exclusion(
                "hour_component_unusable",
                HOURS_UNUSABLE_SQL,
                "Regular Hours, Overtime or Double Time is missing or not a number",
            ),
        ),
    ),
    Metric(
        id="employee_label_count",
        label="Employee labels",
        definition="Distinct Employee labels after trimming, case-folding and collapsing whitespace. A count of labels, not of verified people; Aliases do not merge labels here.",
        unit="employee labels",
        grain="Employee label",
        aggregation="count_distinct",
        null_treatment="A Ticket with no Employee text is left out and reported.",
        exclusions_text=("Tickets with an empty Employee cell",),
        lineage="The Employee cell of every contributing Ticket.",
        value="t.employee_label",
        exclusions=(Exclusion("employee_missing", "t.employee_label IS NULL", "Employee is empty"),),
    ),
    Metric(
        id="submission_lag_days",
        label="Submission lag",
        definition="The calendar date of Created minus Date as recorded, in whole days, when both dates are usable.",
        unit="days",
        grain="Ticket",
        aggregation="distribution",
        null_treatment="A Ticket with an unusable Date or Created is excluded and counted.",
        exclusions_text=(
            "Date or Created is missing or not a date",
            "Negative lag (work dated after its submission) is a separate exception, not discarded silently",
        ),
        lineage="Each contributing Ticket's Date and Created cells.",
        measured_on="Date as recorded to Created",
        value="date_diff('day', CAST(t.work_date AS DATE), CAST(t.created AS DATE))",
        exclusions=(
            Exclusion("date_unusable", "t.work_date IS NULL OR t.created IS NULL", "Date or Created is missing or not a date"),
            Exclusion(
                "negative_lag",
                "CAST(t.work_date AS DATE) > CAST(t.created AS DATE)",
                "Date as recorded falls after Created",
            ),
        ),
    ),
    Metric(
        id="observed_approval_interval_hours",
        label="Observed approval interval",
        definition="Date Approved minus Created, in hours, for Approved Tickets with valid nonnegative timestamps. Not a stage duration, and never applied to Rejected Tickets.",
        unit="hours",
        grain="Ticket",
        aggregation="distribution",
        null_treatment="An Approved Ticket with an unusable Created or Date Approved is excluded and counted.",
        exclusions_text=(
            "Tickets that are not Approved",
            "Created or Date Approved is missing or not a date",
            "Date Approved before Created is a separate exception",
        ),
        lineage="Each contributing Ticket's Created and Date Approved cells.",
        measured_on="Created to Date Approved",
        scope="t.status = 'Approved'",
        value="date_diff('second', t.created, t.date_approved) / 3600.0",
        exclusions=(
            Exclusion(
                "timestamp_unusable",
                "t.created IS NULL OR t.date_approved IS NULL",
                "Created or Date Approved is missing or not a date",
            ),
            Exclusion("negative_interval", "t.date_approved < t.created", "Date Approved falls before Created"),
        ),
        requires_columns=("Date Approved",),
    ),
    Metric(
        id="known_base_value_bbd",
        label="Known base-value components",
        definition=(
            "Recorded Rate × claimed hours + Job Work Pay, rounded half-up to cents per Ticket and then summed, "
            "in BBD. A partial valuation of submissions: not an amount paid, saved or owed."
        ),
        unit="BBD",
        grain="Ticket",
        aggregation="sum",
        null_treatment=(
            "Claimed labour on a Ticket with no usable Rate or hours is unpriced and disclosed, never valued at zero; "
            "its Job Work Pay still counts. A Ticket with no known component is left out and reported."
        ),
        exclusions_text=("Tickets with neither priceable labour nor a usable Job Work Pay",),
        lineage="Each contributing Ticket's Rate, hour and Job Work Pay cells.",
        value=(
            f"ROUND(COALESCE(CASE WHEN {LABOUR_KNOWN_SQL} THEN {LABOUR_VALUE_SQL} END, 0)"
            " + COALESCE(CAST(t.job_work_pay AS DECIMAL(18, 4)), 0), 2)"
        ),
        exclusions=(
            Exclusion(
                "no_known_component",
                f"NOT {LABOUR_KNOWN_SQL} AND t.job_work_pay IS NULL",
                "neither labour nor Job Work Pay can be valued",
            ),
        ),
        partials=(
            Partial(
                "unpriced_labour",
                f"NOT {LABOUR_KNOWN_SQL}",
                "labour is unpriced because Rate or an hour component is missing or invalid",
                quantity=USABLE_HOURS_SQL,
                quantity_unit="hours",
            ),
        ),
        requires_columns=("Rate",),
    ),
)

METRICS: dict[str, Metric] = {metric.id: metric for metric in REGISTRY}


class MetricError(ValueError):
    """A metric request outside the registry's allowlist."""

    def __init__(self, code: str, field_name: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.field = field_name
        self.status = status

    def payload(self) -> dict[str, str]:
        return {"code": self.code, "field": self.field, "message": str(self)}


def registry_payload(fields: tuple[str, ...] | list[str]) -> list[dict[str, Any]]:
    return [metric.payload(fields) for metric in REGISTRY]


def evaluate(
    connection: duckdb.DuckDBPyConnection,
    fingerprint: str,
    fields: tuple[str, ...] | list[str],
    metric: Metric,
    filters: Filters,
    as_of: dt.date,
    group_by: str | None = None,
    include_rows: bool = False,
) -> dict[str, Any]:
    """One metric's value under the filters, with its coverage, warnings and (optionally) source rows."""
    if group_by is not None:
        if group_by not in metric.allowed_dimensions:
            raise MetricError(
                "unsupported_dimension", "group_by", f"{metric.id} cannot be grouped by {group_by!r}; "
                f"allowed: {', '.join(metric.allowed_dimensions) or 'none'}"
            )
        if group_by not in fields:
            raise MetricError("unsupported_dimension", "group_by", f"the workbook has no {group_by} column to group by")
    availability = metric.availability(fields)
    result: dict[str, Any] = {
        "metric": {
            "id": metric.id, "label": metric.label, "definition": metric.definition,
            "unit": metric.unit, "grain": metric.grain,
        },
        "availability": availability,
        "statistic": metric.statistic,
        "grain": metric.grain,
        "group_by": group_by,
        "filters": filters.payload(),
        "value": None,
        "summary": None,
        "percentage": None,
        "groups": None,
        "buckets": None,
        "coverage": None,
        "warnings": [],
    }
    if availability["status"] != "available":
        result["warnings"].append(availability["reason"])
        return result

    if metric.aggregation == "possible_duplicate_count":
        result.update(_unflagged_exact_repeats(connection, fingerprint, filters, include_rows))
        return result

    scoped_sql, parameters = _scoped(metric, fingerprint, filters, as_of, group_by)
    totals = _aggregate(connection, metric, scoped_sql, parameters, grouped=False)
    total = totals[0] if totals else _empty_aggregate(metric)
    result["value"] = total["value"]
    result["summary"] = total.get("summary")
    if group_by is not None:
        result["groups"] = _aggregate(connection, metric, scoped_sql, parameters, grouped=True)
    if metric.buckets:
        result["buckets"] = _bucket_counts(connection, metric, scoped_sql, parameters)
    result["coverage"] = _coverage(connection, metric, scoped_sql, parameters, total["contributing_tickets"])
    result["warnings"] = _coverage_warnings(metric, result["coverage"])
    if metric.share_of is not None:
        denominator = evaluate(connection, fingerprint, fields, METRICS[metric.share_of], filters, as_of)["value"]
        result["percentage"] = {
            "numerator": result["value"],
            "denominator": denominator,
            "denominator_metric": metric.share_of,
            "ratio": (result["value"] / denominator) if denominator else None,
        }
    if include_rows:
        rows = connection.execute(
            f"{scoped_sql} SELECT excel_row FROM scoped WHERE excluded_by IS NULL ORDER BY excel_row", parameters
        ).fetchall()
        result["contributing_rows"] = [row[0] for row in rows]
    return result


def bucket_rows(
    connection: duckdb.DuckDBPyConnection,
    fingerprint: str,
    fields: tuple[str, ...] | list[str],
    metric: Metric,
    filters: Filters,
    as_of: dt.date,
    bucket_id: str,
) -> dict[str, Any]:
    """The Tickets one bucket of a metric counts, with each Ticket's value: highest value first, then earliest Created.

    The same scoped rows as `evaluate`, under the same filters and as-of
    date, so the listing always holds the bucket's count.
    """
    if not metric.buckets:
        raise MetricError("no_buckets", "metric_id", f"{metric.id} is not counted by buckets", status=404)
    bucket = next((bucket for bucket in metric.buckets if bucket.id == bucket_id), None)
    if bucket is None:
        raise MetricError(
            "unknown_bucket", "bucket_id",
            f"{metric.id} has no bucket {bucket_id!r}; buckets: {', '.join(item.id for item in metric.buckets)}",
            status=404,
        )
    availability = metric.availability(fields)
    rows: list[tuple[Any, ...]] = []
    if availability["status"] == "available":
        scoped_sql, parameters = _scoped(metric, fingerprint, filters, as_of, None)
        rows = connection.execute(
            f"""{scoped_sql} SELECT s.excel_row, t.ticket_number, t.employee_name, t.work_date, t.created,
                t.status, t.keyed, s.metric_value
            FROM scoped s JOIN ticket_values t ON t.snapshot_fingerprint = $fingerprint AND t.excel_row = s.excel_row
            WHERE s.excluded_by IS NULL AND {bucket.predicate("s.metric_value")}
            ORDER BY s.metric_value DESC, t.created NULLS LAST, s.excel_row""",
            parameters,
        ).fetchall()
    return {
        "metric": {"id": metric.id, "label": metric.label, "definition": metric.definition, "unit": metric.unit},
        "availability": availability,
        "bucket": bucket.payload(),
        "grain": metric.grain,
        "filters": filters.payload(),
        "tickets": len(rows),
        "rows": [
            {
                "excel_row": excel_row,
                "ticket_number": ticket_number,
                "employee": employee,
                "date": work_date.date().isoformat() if work_date is not None else None,
                "created": created.isoformat() if created is not None else None,
                "status": status,
                "keyed": keyed,
                "value": _number(value),
            }
            for excel_row, ticket_number, employee, work_date, created, status, keyed, value in rows
        ],
    }


def _bucket_counts(
    connection: duckdb.DuckDBPyConnection, metric: Metric, scoped_sql: str, parameters: dict[str, Any]
) -> list[dict[str, Any]]:
    """Contributing Tickets per bucket, every bucket listed in order and an empty one as zero."""
    case = " ".join(f"WHEN {bucket.predicate()} THEN '{bucket.id}'" for bucket in metric.buckets)
    counted = dict(connection.execute(
        f"{scoped_sql} SELECT CASE {case} END AS bucket, count(*) FROM scoped WHERE excluded_by IS NULL GROUP BY bucket",
        parameters,
    ).fetchall())
    return [{**bucket.payload(), "tickets": counted.get(bucket.id, 0)} for bucket in metric.buckets]


def _unflagged_exact_repeats(
    connection: duckdb.DuckDBPyConnection, fingerprint: str, filters: Filters, include_rows: bool
) -> dict[str, Any]:
    """Strict repeat groups with no flagged duplicate and every member Approved and Keyed.

    A group counts when any member is inside the filters, and then all its
    members are listed, so a comparison is never truncated by a filter.
    """
    filter_sql, parameters = filters.sql("t")
    parameters = {**parameters, "fingerprint": fingerprint}
    possible_duplicates, tickets, rows = connection.execute(
        f"""WITH strict AS ({strict_groups_sql()}), members AS (
            SELECT s.strict_group, t.excel_row, t.status, t.keyed,
                COALESCE({FLAGGED_DUPLICATE_SCOPE}, false) AS flagged, COALESCE({filter_sql}, false) AS in_filter
            FROM strict s JOIN ticket_values t ON t.snapshot_fingerprint = $fingerprint AND t.excel_row = s.excel_row
        ), qualifying AS (
            SELECT strict_group FROM members GROUP BY strict_group
            HAVING bool_and(COALESCE(status = 'Approved' AND keyed, false)) AND NOT bool_or(flagged) AND bool_or(in_filter)
        )
        SELECT count(DISTINCT strict_group), count(*), list(excel_row ORDER BY excel_row)
        FROM members WHERE strict_group IN (SELECT strict_group FROM qualifying)""",
        parameters,
    ).fetchone()
    incomplete = " OR ".join(f"t.{column} IS NULL" for column in STRICT_KEY.values())
    uncompared, uncompared_rows = connection.execute(
        "SELECT count(*), list(t.excel_row ORDER BY t.excel_row) FROM ticket_values t"
        f" WHERE t.snapshot_fingerprint = $fingerprint AND ({filter_sql}) AND ({incomplete})",
        parameters,
    ).fetchone()
    excluded = []
    warnings = []
    if uncompared:
        message = "a strict comparison field (Employee, Date, Job Number, Time or a claim component) is missing or invalid"
        excluded.append({"code": "comparison_field_unusable", "message": message, "tickets": uncompared, "excel_rows": list(uncompared_rows or [])})
        warnings.append(
            f"{uncompared} Ticket{'s' if uncompared != 1 else ''} could not be compared because {message} "
            f"(Excel row{'s' if uncompared != 1 else ''} {_rows_text(list(uncompared_rows or []))}); "
            "they are never treated as matching."
        )
    result: dict[str, Any] = {
        "value": possible_duplicates,
        "tickets": tickets,
        "coverage": {"contributing_tickets": tickets, "excluded": excluded, "partial": []},
        "warnings": warnings,
    }
    if include_rows:
        result["contributing_rows"] = list(rows or [])
    return result


def _scoped(
    metric: Metric, fingerprint: str, filters: Filters, as_of: dt.date, group_by: str | None
) -> tuple[str, dict[str, Any]]:
    """A WITH clause defining `scoped`: one row per in-scope Ticket with its value and any exclusion."""
    filter_sql, parameters = filters.sql("t")
    parameters = {**parameters, "fingerprint": fingerprint}
    if "$as_of" in metric.value or any("$as_of" in item.predicate for item in metric.exclusions):
        parameters["as_of"] = as_of
    excluded = " ".join(f"WHEN {item.predicate} THEN '{item.code}'" for item in metric.exclusions)
    partial = " ".join(f"WHEN {item.predicate} THEN '{item.code}'" for item in metric.partials)
    quantity = " ".join(
        f"WHEN {item.predicate} THEN {item.quantity}" for item in metric.partials if item.quantity is not None
    )
    group_key = f"t.{DIMENSIONS[group_by]}" if group_by is not None else "NULL"
    sql = f"""WITH base AS (
        SELECT t.*, {f"CASE {excluded} END" if excluded else "NULL"} AS excluded_by
        FROM ticket_values t
        WHERE t.snapshot_fingerprint = $fingerprint AND ({filter_sql}) AND ({metric.scope})
    ), scoped AS (
        SELECT t.excel_row, t.excluded_by, {group_key} AS group_key,
            CASE WHEN t.excluded_by IS NULL THEN {metric.value} END AS metric_value,
            {f"CASE {partial} END" if partial else "NULL"} AS partial_by,
            {f"CASE {quantity} END" if quantity else "NULL"} AS partial_quantity
        FROM base t
    )"""
    return sql, parameters


def _aggregate(
    connection: duckdb.DuckDBPyConnection, metric: Metric, scoped_sql: str, parameters: dict[str, Any], grouped: bool
) -> list[dict[str, Any]]:
    if metric.aggregation == "count":
        columns = "count(*)"
    elif metric.aggregation == "count_distinct":
        columns = "count(DISTINCT metric_value)"
    elif metric.aggregation == "sum":
        columns = "sum(metric_value)"
    else:
        columns = "quantile_cont(metric_value, 0.5), min(metric_value), max(metric_value), avg(metric_value)"
    key = "group_key" if grouped else "NULL"
    rows = connection.execute(
        f"{scoped_sql} SELECT {key} AS key, count(*) AS contributing, {columns}"
        f" FROM scoped WHERE excluded_by IS NULL {'GROUP BY group_key' if grouped else ''}",
        parameters,
    ).fetchall()
    aggregates = []
    for key_value, contributing, *values in rows:
        if not grouped and contributing == 0:
            continue
        entry: dict[str, Any] = {"contributing_tickets": contributing, "value": _number(values[0])}
        if metric.aggregation == "distribution":
            entry["summary"] = {
                "count": contributing,
                "median": _number(values[0]),
                "min": _number(values[1]),
                "max": _number(values[2]),
                "mean": _number(values[3]),
            }
        if grouped:
            entry = {"key": key_value, **entry}
        aggregates.append(entry)
    if grouped:
        aggregates.sort(key=lambda entry: (-(entry["value"] or 0), str(entry["key"])))
    return aggregates


def _empty_aggregate(metric: Metric) -> dict[str, Any]:
    """The value over no contributing Tickets: zero for counts and sums, no median for a distribution."""
    if metric.aggregation == "distribution":
        return {"contributing_tickets": 0, "value": None, "summary": {"count": 0, "median": None, "min": None, "max": None, "mean": None}}
    return {"contributing_tickets": 0, "value": 0}


def _coverage(
    connection: duckdb.DuckDBPyConnection,
    metric: Metric,
    scoped_sql: str,
    parameters: dict[str, Any],
    contributing: int,
) -> dict[str, Any]:
    messages = {item.code: item.message for item in (*metric.exclusions, *metric.partials)}
    units = {item.code: item.quantity_unit for item in metric.partials}
    excluded = connection.execute(
        f"{scoped_sql} SELECT excluded_by, count(*), list(excel_row ORDER BY excel_row)"
        " FROM scoped WHERE excluded_by IS NOT NULL GROUP BY excluded_by ORDER BY excluded_by",
        parameters,
    ).fetchall()
    partial = connection.execute(
        f"{scoped_sql} SELECT partial_by, count(*), list(excel_row ORDER BY excel_row), sum(partial_quantity)"
        " FROM scoped WHERE excluded_by IS NULL AND partial_by IS NOT NULL GROUP BY partial_by ORDER BY partial_by",
        parameters,
    ).fetchall()
    return {
        "contributing_tickets": contributing,
        "excluded": [
            {"code": code, "message": messages[code], "tickets": count, "excel_rows": list(rows)}
            for code, count, rows in excluded
        ],
        "partial": [
            {
                "code": code, "message": messages[code], "tickets": count, "excel_rows": list(rows),
                "quantity": _number(quantity), "quantity_unit": units[code],
            }
            for code, count, rows, quantity in partial
        ],
    }


def _coverage_warnings(metric: Metric, coverage: dict[str, Any]) -> list[str]:
    warnings = []
    for item in coverage["excluded"]:
        warnings.append(
            f"{item['tickets']} Ticket{'s' if item['tickets'] != 1 else ''} left out of {metric.label.lower()} "
            f"because {item['message']} (Excel row{'s' if item['tickets'] != 1 else ''} "
            f"{_rows_text(item['excel_rows'])}); they are not counted as zero."
        )
    for item in coverage["partial"]:
        quantity = f", {_format(item['quantity'])} {item['quantity_unit']}" if item["quantity"] is not None else ""
        warnings.append(
            f"{item['tickets']} Ticket{'s' if item['tickets'] != 1 else ''} contribute only part of their value "
            f"because {item['message']}{quantity}."
        )
    return warnings


def _rows_text(rows: list[int], limit: int = 10) -> str:
    shown = ", ".join(str(row) for row in rows[:limit])
    return shown if len(rows) <= limit else f"{shown} and {len(rows) - limit} more"


def _number(value: Any) -> Any:
    """Exact decimals become plain JSON numbers: integral values as int, others as float."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _format(value: Any) -> str:
    return f"{value:,}" if isinstance(value, int) else f"{value:,.2f}"
