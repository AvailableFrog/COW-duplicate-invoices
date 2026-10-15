"""Explore query plans (PRD section 7): validate, compile and shape the result of a typed plan.

A plan names what to chart, never how to compute it: a registry metric, at
most one grouping (a Ticket field, or a week or month of the date basis),
field conditions, a date basis and an absolute or relative range, a chart
template, a sort, a bar limit and whether the rest are combined as Other.
Its nine fields are all required, so nothing is assumed silently.
`validate` checks every one against an allowlist, and the fields against
each other (a line needs ordered dates, a histogram a distribution), and
reports every problem at once as a structured, recoverable issue naming the
field at fault and, where it helps, the values that are allowed.
`compile_filters` turns a valid plan, any inherited Overview filters and the
as-of date (which a relative range resolves against) into the registry's
Filters, whose SQL is parameterized and executed by `metrics.evaluate`
inside a read-only transaction (store.evaluate_plan); a plan never carries
SQL, a column name outside the allowlist or a chart specification. `result`
shapes the evaluated metric into bars, periods, bins or points, the full
table, lineage, the "How this was calculated" panel and a trusted chart
template (chart_templates.py); `drilldown` lists exactly the Tickets behind
the chart or one of its marks, from the same evaluation.

The Snapshot fingerprint, the as-of date, the versions and the inherited
filters are attached to every response beside the plan, never inside it,
so neither the chips nor a release-two provider can change them.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field
from typing import Any

from labour_ticket_analytics import chart_templates
from labour_ticket_analytics.chart_templates import Bar, Bin, Dot, Point
from labour_ticket_analytics.filters import (
    DATE_BASES, DEFAULT_DATE_BASIS, OPERATORS, TICKET_FIELDS, Condition, FilterError, Filters,
)
from labour_ticket_analytics.metrics import METRICS, OUTSIDE_WINDOW_KEY, REGISTRY, TIME_GROUPINGS, Metric
from labour_ticket_analytics.metrics import _rows_text
from labour_ticket_analytics.schema import OPTIONAL_COLUMNS, REQUIRED_COLUMNS

PLAN_FIELDS = (
    "metric_id", "group_by", "filters", "date_basis", "date_range", "chart", "sort", "limit", "include_other",
)
FILTER_KEYS = ("field", "operator", "value")
# Only additive statistics can be split into bars: a group's share of Other is then exactly the sum of the
# groups it holds. A distribution of per-ticket values is drawn as a histogram instead (decision-log entry 79).
AGGREGATIONS = ("count", "sum")
DISTRIBUTION = "distribution"
SORTS: dict[str, str] = {
    "metric_desc": "Largest first", "metric_asc": "Smallest first", "label_asc": "A to Z, or in date or value order",
}
# The one sort an ordered chart (weeks, months, histogram bins, scatter points) accepts: its axis order.
ORDERED_SORT = "label_asc"
MIN_LIMIT, MAX_LIMIT, DEFAULT_LIMIT = 1, 25, 10
MAX_GROUPINGS = 1
MAX_FILTERS = 10
SOURCE_COLUMNS = (*REQUIRED_COLUMNS, *OPTIONAL_COLUMNS)
GROUPINGS = (*TICKET_FIELDS, *TIME_GROUPINGS)
# A scatterplot's x metric and the registry metric drawn against it on y, both one value per Ticket
# (decision-log entry 81): claimed hours against the base value they were priced at.
SCATTER_PAIRS: dict[str, str] = {"claimed_hours": "known_base_value_bbd"}
# Relative date ranges, resolved against the analytical as-of date (decision-log entry 82).
RELATIVE_RANGES: dict[str, str] = {
    "last_7_days": "Last 7 days",
    "last_30_days": "Last 30 days",
    "last_90_days": "Last 90 days",
    "this_month": "This month, to the as-of date",
    "previous_month": "Previous calendar month",
}
# A histogram has at most this many equal bins; the width is the smallest of 1, 2, 5, 10, 20, 50, ... that fits.
MAX_BINS = 40

BLANK_ID = "__blank__"
BLANK_LABEL = "Blank or unreadable"
OTHER_ID = "__other__"
TOTAL_ID = "__total__"
OUTSIDE_ID = "__outside__"

# How a grouping's categories are counted in words: one and many.
DIMENSION_NOUNS: dict[str, tuple[str, str]] = {
    "Approval Status": ("status", "statuses"),
    "Keyed": ("Keyed value", "Keyed values"),
    "Job Number": ("job", "jobs"),
    "Job Name": ("job name", "job names"),
    "Supervisor": ("supervisor", "supervisors"),
    "Occupation": ("occupation", "occupations"),
    "Week": ("week", "weeks"),
    "Month": ("month", "months"),
}

# What a grouping does not show, stated beside the chart (PRD sections 3 and 7).
DIMENSION_NOTES: dict[str, str] = {
    "Approval Status": "Approval Status is each ticket's current recorded status, not a payment status.",
    "Keyed": "Keyed is recorded separately from approval and does not show that a payment was made.",
    "Job Number": "Each job is named by the Job Name most often recorded with its number.",
    "Job Name": (
        "Job Name is free text as entered, so one job can appear under several spellings; "
        "group by Job Number to count each job once."
    ),
    "Supervisor": (
        "Counts the tickets recorded under each supervisor. It says nothing about supervisor performance "
        "or who caused a delay."
    ),
}


@dataclass(frozen=True)
class PlanIssue:
    """One recoverable problem with a plan: what failed, the plan field at fault and what is allowed instead."""

    code: str
    field: str
    message: str
    allowed: list[Any] | None = None

    def payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "field": self.field, "message": self.message}
        if self.allowed is not None:
            payload["allowed"] = self.allowed
        return payload


class PlanError(ValueError):
    """A plan outside the allowlist; carries every issue found."""

    def __init__(self, issues: list[PlanIssue]) -> None:
        super().__init__("; ".join(issue.message for issue in issues))
        self.issues = issues

    def payload(self) -> dict[str, Any]:
        count = len(self.issues)
        return {
            "code": "invalid_plan",
            "field": "plan",
            "message": f"The plan cannot run: {count} problem{'s' if count != 1 else ''} to fix. {self.issues[0].message}",
            "errors": [issue.payload() for issue in self.issues],
        }


@dataclass(frozen=True)
class Plan:
    metric_id: str
    group_by: tuple[str, ...]
    conditions: tuple[Condition, ...]
    date_basis: str
    date_from: dt.date | None
    date_to: dt.date | None
    chart: str
    sort: str
    limit: int
    include_other: bool
    # A relative range ("last_30_days"), resolved against the as-of date when the plan is compiled.
    date_relative: str | None = None

    @property
    def metric(self) -> Metric:
        return METRICS[self.metric_id]

    @property
    def paired_metric(self) -> Metric | None:
        return METRICS[SCATTER_PAIRS[self.metric_id]] if self.form == "pair" else None

    @property
    def dimension(self) -> str | None:
        return self.group_by[0] if self.group_by else None

    @property
    def time_grouping(self) -> bool:
        return self.dimension in TIME_GROUPINGS

    @property
    def has_date_range(self) -> bool:
        return self.date_relative is not None or self.date_from is not None or self.date_to is not None

    @property
    def form(self) -> str:
        """What the plan draws: one total, categories, ordered periods, a distribution or a pair of values."""
        if self.metric.aggregation == DISTRIBUTION:
            return "distribution"
        if self.chart == "scatter":
            return "pair"
        if self.time_grouping:
            return "dates"
        return "categories" if self.dimension else "total"

    def payload(self) -> dict[str, Any]:
        """The plan as validated, in the shape it was written."""
        return {
            "metric_id": self.metric_id,
            "group_by": list(self.group_by),
            "filters": [
                {"field": condition.field, "operator": condition.operator, "value": condition.value}
                for condition in self.conditions
            ],
            "date_basis": self.date_basis,
            "date_range": (
                {"relative": self.date_relative} if self.date_relative else
                {
                    "from": self.date_from.isoformat() if self.date_from else None,
                    "to": self.date_to.isoformat() if self.date_to else None,
                }
                if self.has_date_range else None
            ),
            "chart": self.chart,
            "sort": self.sort,
            "limit": self.limit,
            "include_other": self.include_other,
        }


@dataclass(frozen=True)
class Inherited:
    """The filters a plan runs under besides its own: the Overview's, when the consultant chose to use them."""

    filters: Filters | None = None

    def payload(self) -> dict[str, Any]:
        if self.filters is None:
            return {"source": "none", "label": "All data", "filters": None}
        return {"source": "overview", "label": "Overview filters", "filters": self.filters.payload()}


def explorable(metric: Metric) -> bool:
    """A registry metric Explore can draw: one value per Ticket, additive (bars) or a distribution (histogram)."""
    return (
        metric.grain == "Ticket" and metric.aggregation in (*AGGREGATIONS, DISTRIBUTION)
        and bool(metric.allowed_dimensions)
    )


EXPLORE_METRICS = tuple(metric for metric in REGISTRY if explorable(metric))


def validate(raw: Any, fields: tuple[str, ...] | list[str]) -> Plan:
    """The plan, checked field by field against the allowlists for a Snapshot with these source fields.

    Raises PlanError listing every issue found, so the chips (or a provider)
    can correct them all at once.
    """
    if not isinstance(raw, dict):
        raise PlanError([PlanIssue("invalid_plan_value", "plan", "The plan must be an object with the nine plan fields.")])
    issues: list[PlanIssue] = []
    for key in raw:
        if key not in PLAN_FIELDS:
            issues.append(PlanIssue(
                "unknown_plan_field", str(key), f"{key!r} is not a plan field; a plan has only these fields.",
                list(PLAN_FIELDS),
            ))
    for key in PLAN_FIELDS:
        if key not in raw:
            issues.append(PlanIssue("missing_plan_field", key, f"The plan has no {key}; every plan field is required."))

    metric = _metric(raw, fields, issues) if "metric_id" in raw else None
    group_by = _group_by(raw, metric, fields, issues) if "group_by" in raw else ()
    conditions = _conditions(raw, fields, issues) if "filters" in raw else ()
    date_basis = _date_basis(raw, fields, issues) if "date_basis" in raw else None
    date_from, date_to, relative = _date_range(raw, issues) if "date_range" in raw else (None, None, None)
    chart = _choice(raw, "chart", chart_templates.TEMPLATES, "unsupported_chart", "chart", issues)
    sort = _choice(raw, "sort", SORTS, "unsupported_sort", "sort", issues)
    limit = _limit(raw, issues) if "limit" in raw else None
    include_other = raw.get("include_other")
    if "include_other" in raw and not isinstance(include_other, bool):
        issues.append(PlanIssue("invalid_plan_value", "include_other", "include_other must be true or false."))
        include_other = None
    if metric is not None:
        _compatibility(metric, raw.get("group_by"), chart, sort, include_other, fields, issues)

    if issues:
        raise PlanError(issues)
    return Plan(
        metric_id=raw["metric_id"],
        group_by=group_by,
        conditions=conditions,
        date_basis=date_basis,
        date_from=date_from,
        date_to=date_to,
        chart=chart,
        sort=sort,
        limit=limit,
        include_other=include_other,
        date_relative=relative,
    )


def _compatibility(
    metric: Metric,
    group_by: Any,
    chart: str | None,
    sort: str | None,
    include_other: bool | None,
    fields: tuple[str, ...] | list[str],
    issues: list[PlanIssue],
) -> None:
    """The plan's fields checked against each other: each chart draws only the forms it is made for.

    A line joins ordered dates and never unordered categories; a histogram
    draws a distribution of per-ticket values, which is never split into bars
    or groups; a scatterplot draws a registry pair; an ordered chart keeps its
    axis order and has no Other.
    """
    grouping = group_by[0] if isinstance(group_by, list) and len(group_by) == 1 else None
    timed = grouping in TIME_GROUPINGS
    distribution = metric.aggregation == DISTRIBUTION
    if distribution and isinstance(group_by, list) and group_by:
        issues.append(PlanIssue(
            "unsupported_aggregation", "group_by",
            f"{metric.label} is a distribution of one value per ticket; it is drawn as one histogram and cannot be "
            "grouped or split into bars. Remove the grouping.",
            [],
        ))
    if chart is not None:
        template = chart_templates.TEMPLATES[chart]
        if distribution:
            form = "distribution"
        elif chart == "scatter":
            form = "pair"
        elif timed:
            form = "dates"
        else:
            form = "categories" if grouping else "total"
        allowed = [item.id for item in chart_templates.TEMPLATES.values() if form in item.forms]
        if chart == "scatter" and not distribution and metric.id not in SCATTER_PAIRS:
            issues.append(PlanIssue(
                "unsupported_chart", "chart",
                f"A scatterplot plots a pair of values per ticket; the registry pairs only "
                f"{', '.join(METRICS[key].label.lower() for key in SCATTER_PAIRS)} with a second value.",
                [item for item in allowed if item != "scatter"],
            ))
        elif chart == "scatter" and grouping is not None:
            issues.append(PlanIssue(
                "unsupported_dimension", "group_by", "A scatterplot plots one point per ticket; remove the grouping.", [],
            ))
        elif chart == "scatter" and not distribution:
            paired = METRICS[SCATTER_PAIRS[metric.id]]
            availability = paired.availability(fields)
            if availability["status"] != "available":
                issues.append(PlanIssue("metric_unavailable", "chart", availability["reason"]))
        elif form not in template.forms:
            reason = {
                "line": "A line joins points in date order, so it needs a Week or Month grouping; it never connects "
                        "unordered categories.",
                "histogram": "A histogram shows how one value per ticket is distributed; choose a distribution metric "
                             "such as submission lag.",
            }.get(chart, f"{template.label} cannot draw {'a distribution' if distribution else 'this plan'}.")
            issues.append(PlanIssue("unsupported_chart", "chart", reason, allowed))
    ordered = timed or distribution or chart == "scatter"
    if ordered and sort is not None and sort != ORDERED_SORT:
        issues.append(PlanIssue(
            "unsupported_sort", "sort",
            "Weeks, months, histogram bins and scatter points keep their own date or value order; choose "
            f"{ORDERED_SORT!r} ({SORTS[ORDERED_SORT]}).",
            [ORDERED_SORT],
        ))
    if ordered and include_other:
        issues.append(PlanIssue(
            "invalid_plan_value", "include_other",
            "Other combines categories; weeks, months, bins and points are never combined. Set include_other to false.",
        ))


def overview_inherited(query: dict[str, Any]) -> dict[str, Any]:
    """The Overview filter bar's query state, as the raw `inherited` object a plan request carries.

    The Overview panels built from plans (release 1.1) run under these, so their drilldowns can be requested
    with the same object.
    """
    return {
        "date_basis": query["date_basis"],
        "date_from": query["date_from"].isoformat() if query["date_from"] else None,
        "date_to": query["date_to"].isoformat() if query["date_to"] else None,
        "jobs": list(query["jobs"]),
        "statuses": list(query["statuses"]),
    }


def inherited(raw: Any, fields: tuple[str, ...] | list[str]) -> Inherited:
    """The Overview filters a plan inherits, as the filter bar holds them; None means "Start with all data"."""
    if raw is None:
        return Inherited()
    if not isinstance(raw, dict):
        raise PlanError([PlanIssue("invalid_plan_value", "inherited", "The inherited filters must be an object or null.")])
    jobs = raw.get("jobs") or []
    if not isinstance(jobs, list) or not all(
        isinstance(job, int) and not isinstance(job, bool) and abs(job) < 2**63 for job in jobs
    ):
        raise PlanError([PlanIssue("invalid_inherited_filter", "inherited.jobs", "jobs must be a list of whole numbers.")])
    try:
        return Inherited(Filters.build(
            fields=fields,
            date_basis=raw.get("date_basis") or DEFAULT_DATE_BASIS,
            date_from=_iso_date(raw.get("date_from")),
            date_to=_iso_date(raw.get("date_to")),
            jobs=jobs,
            statuses=list(raw.get("statuses") or []),
        ))
    except (FilterError, ValueError, TypeError) as error:
        field_name = f"inherited.{error.field}" if isinstance(error, FilterError) else "inherited"
        raise PlanError([PlanIssue("invalid_inherited_filter", field_name, str(error))]) from error


def resolve_relative(relative: str, as_of: dt.date) -> tuple[dt.date, dt.date]:
    """A relative range's inclusive dates as of the analytical as-of date, which is the range's last day.

    "Last N days" is the N days ending on the as-of date; "this month" runs from
    its first day to the as-of date; "previous month" is the whole calendar month
    before the as-of date's.
    """
    if relative.startswith("last_"):
        days = int(relative.split("_")[1])
        return as_of - dt.timedelta(days=days - 1), as_of
    first = as_of.replace(day=1)
    if relative == "this_month":
        return first, as_of
    last = first - dt.timedelta(days=1)
    return last.replace(day=1), last


def compile_filters(
    plan: Plan, inheritance: Inherited, fields: tuple[str, ...] | list[str], as_of: dt.date,
) -> Filters:
    """The registry Filters a plan runs under: its conditions and date range, and the inherited jobs, statuses and range.

    A relative range resolves against the as-of date. Two date ranges are
    never combined or one silently dropped: a plan with its own range under
    Overview filters that also hold one is refused.
    """
    parent = inheritance.filters
    if plan.has_date_range:
        if parent is not None and parent.has_date_range:
            raise PlanError([PlanIssue(
                "date_range_conflict", "date_range",
                f"The Overview filters already limit {DATE_BASES[parent.date_basis][1]} to a range, so the plan "
                "cannot add a range of its own. Remove the plan's date range, or choose Start with all data.",
            )])
        basis, start, end = plan.date_basis, plan.date_from, plan.date_to
        if plan.date_relative:
            start, end = resolve_relative(plan.date_relative, as_of)
    elif parent is not None and parent.has_date_range:
        basis, start, end = parent.date_basis, parent.date_from, parent.date_to
    else:
        basis, start, end = plan.date_basis, None, None
    return Filters.build(
        fields=fields,
        date_basis=basis,
        date_from=start,
        date_to=end,
        jobs=parent.jobs if parent else (),
        statuses=parent.statuses if parent else (),
        conditions=plan.conditions,
    )


@dataclass
class _Group:
    id: str
    key: Any
    label: str
    value: Any
    contributing_tickets: int
    excel_rows: list[int] = field(default_factory=list)
    in_other: bool = False
    shown: bool = False
    # A period's short axis label, or a histogram bin's half-open range [min, max).
    tick: str | None = None
    bin: dict[str, Any] | None = None

    def payload(self) -> dict[str, Any]:
        payload = {
            "id": self.id, "key": self.key, "label": self.label, "value": self.value,
            "contributing_tickets": self.contributing_tickets, "excel_rows": self.excel_rows,
            "shown": self.shown, "in_other": self.in_other,
        }
        if self.bin is not None:
            payload["bin"] = self.bin
        return payload


@dataclass
class Executed:
    """An executed plan: the response payload and, kept beside it, each contributing Ticket's own value.

    The values serve the drilldown and the CSV exports from the same
    evaluation, so a listing always reproduces the chart it came from.
    """

    payload: dict[str, Any]
    values: dict[int, Any]
    paired_values: dict[int, Any] = field(default_factory=dict)

    @property
    def plan(self) -> dict[str, Any]:
        return self.payload["plan"]


def result(
    plan: Plan,
    inheritance: Inherited,
    filters: Filters,
    evaluated: dict[str, Any],
    job_names: dict[int, str | None],
    as_of: dt.date,
    window: tuple[dt.date, dt.date] | None,
    paired: dict[str, Any] | None = None,
) -> Executed:
    """The executed plan: drawn marks, the full table, lineage, warnings, How calculated and the chart."""
    metric = plan.metric
    form = plan.form
    dimension = plan.dimension
    availability = evaluated["availability"]
    if paired is not None and paired["availability"]["status"] != "available":
        availability = paired["availability"]
    available = availability["status"] == "available"
    values: dict[int, Any] = dict(evaluated.get("contributing_values", {})) if available else {}
    paired_values: dict[int, Any] = dict(paired.get("contributing_values", {})) if available and paired else {}
    coverage = evaluated["coverage"]
    warnings = list(evaluated["warnings"])
    notes = [DIMENSION_NOTES[dimension]] if dimension in DIMENSION_NOTES else []
    groups: list[_Group] = []
    rest: list[_Group] = []
    other = None
    points = None
    width = None

    if not available:
        pass
    elif form == "pair":
        coverage, warnings, points = _pair(evaluated, paired, values, paired_values)
    elif form == "distribution":
        groups, width = _bins(values, metric)
    elif form == "dates":
        groups, period_warnings = _periods(evaluated["groups"] or [], plan, window)
        warnings.extend(period_warnings)
        notes.extend(_period_notes(plan))
    elif form == "total":
        if evaluated["coverage"]["contributing_tickets"]:
            groups = [_Group(
                TOTAL_ID, None, "All tickets in the plan", evaluated["value"],
                evaluated["coverage"]["contributing_tickets"], list(evaluated.get("contributing_rows", [])),
            )]
    else:
        groups = _sorted([
            _Group(
                _group_id(entry["key"]), entry["key"], group_label(dimension, entry["key"], job_names),
                entry["value"], entry["contributing_tickets"], list(entry.get("excel_rows", [])),
            )
            for entry in evaluated["groups"] or []
        ], plan.sort, dimension)

    contributing = len(points) if points is not None else (coverage["contributing_tickets"] if coverage else 0)
    empty = not available or contributing == 0
    if empty:
        groups, points = [], [] if form == "pair" else None

    # The marks drawn: the top `limit` categories (and Other), every period, every bin, or every point.
    if form in ("categories", "total"):
        shown, rest = groups[:plan.limit], groups[plan.limit:]
        warnings.extend(_tie_warning(plan, shown, rest))
    elif form == "dates":
        shown = [group for group in groups if group.id not in (OUTSIDE_ID, BLANK_ID)]
    else:
        shown = list(groups)
    for group in shown:
        group.shown = True
    if rest and plan.include_other:
        for group in rest:
            group.in_other = True
        singular, plural = DIMENSION_NOUNS[dimension]
        other = {
            "id": OTHER_ID,
            "label": f"Other ({len(rest)} {singular if len(rest) == 1 else plural})",
            "value": _number_sum(group.value for group in rest),
            "contributing_tickets": sum(group.contributing_tickets for group in rest),
            "groups": len(rest),
            "excel_rows": sorted(row for group in rest for row in group.excel_rows),
        }
    bars = [Bar(group.id, group.label, group.value, _format(group.value, metric)) for group in shown]
    if other is not None:
        bars.append(Bar(OTHER_ID, other["label"], other["value"], _format(other["value"], metric), other=True))

    parent = inheritance.filters
    if parent is not None and parent.has_date_range and parent.date_basis != plan.date_basis:
        warnings.append(
            f"The Overview filters' date range applies to {DATE_BASES[parent.date_basis][1]}; the plan's date basis, "
            f"{DATE_BASES[plan.date_basis][1]}, has no range of its own."
        )

    title = _title(plan)
    counted = form in ("distribution", "pair")
    unit = "tickets" if counted else metric.unit
    value_title = "Tickets" if counted else metric.unit[:1].upper() + metric.unit[1:]
    if empty:
        total = None
    elif counted:
        total = contributing
    else:
        total = evaluated["value"]
    chart = None
    if not empty and chart_templates.TEMPLATES[plan.chart].draws:
        chart = _chart(plan, title, filters, total, contributing, bars, shown, points, metric)
    contributing_rows = sorted(point["excel_row"] for point in points) if points is not None else (
        [] if empty else list(evaluated.get("contributing_rows", []))
    )
    date_range = date_range_payload(plan, filters, as_of)
    payload = {
        "plan": plan.payload(),
        "inherited_filters": inheritance.payload(),
        "filters": filters.payload(),
        "date_range": date_range,
        "metric": {
            "id": metric.id, "label": metric.label, "definition": metric.definition, "unit": metric.unit,
            "statistic": metric.statistic,
        },
        "paired_metric": _metric_payload(plan.paired_metric) if plan.paired_metric else None,
        "availability": availability,
        "title": title,
        "summary": _summary(plan, filters, metric, len(groups), len(rest), width),
        "grain": metric.grain,
        "presentation": "chart" if chart_templates.TEMPLATES[plan.chart].draws else "table",
        "result": {
            "form": form,
            "total": total,
            "contributing_tickets": contributing,
            "unit": unit,
            "value_title": value_title,
            "empty": empty,
            "empty_message": _empty_message(plan, filters, availability) if empty else None,
            "groups": [group.payload() for group in groups],
            "bars": [{"id": bar.id, "label": bar.label, "value": bar.value, "other": bar.other} for bar in bars],
            "other": other,
            "hidden_groups": 0 if plan.include_other else len(rest),
            "percentage": None if empty else evaluated.get("percentage"),
            "summary": evaluated.get("summary") if form == "distribution" and not empty else None,
            "points": points,
            "bin_width": width,
        },
        "chart": chart,
        "lineage": {
            "metric_id": metric.id,
            "metric": metric.lineage,
            "contributing_tickets": contributing,
            "contributing_rows": contributing_rows,
        },
        "coverage": coverage,
        "warnings": warnings,
        "notes": notes,
    }
    payload["how_calculated"] = _how_calculated(plan, payload, inheritance, len(shown), len(rest), width)
    return Executed(payload, values, paired_values)


def date_range_payload(plan: Plan, filters: Filters, as_of: dt.date) -> dict[str, Any] | None:
    """The absolute range the plan ran under, where it came from, and for a relative range what it resolved against."""
    if not filters.has_date_range:
        return None
    own = plan.has_date_range
    return {
        "source": ("relative" if plan.date_relative else "plan") if own else "overview",
        "relative": plan.date_relative if own else None,
        "label": RELATIVE_RANGES[plan.date_relative] if own and plan.date_relative else (
            "Fixed range" if own else "Overview filters"
        ),
        "from": filters.date_from.isoformat() if filters.date_from else None,
        "to": filters.date_to.isoformat() if filters.date_to else None,
        "as_of": as_of.isoformat() if own and plan.date_relative else None,
        "date_basis": filters.date_basis,
        "date_basis_label": DATE_BASES[filters.date_basis][1],
    }


def _metric_payload(metric: Metric) -> dict[str, Any]:
    return {
        "id": metric.id, "label": metric.label, "definition": metric.definition, "unit": metric.unit,
        "statistic": metric.statistic,
    }


def _title(plan: Plan) -> str:
    metric = plan.metric
    if plan.form == "pair":
        return f"{metric.label} against {plan.paired_metric.label.lower()}, per ticket"
    if plan.form == "distribution":
        return f"{metric.label}: distribution per ticket"
    if plan.time_grouping:
        return f"{metric.label} by {plan.dimension.lower()} of {DATE_BASES[plan.date_basis][1]}"
    return f"{metric.label} by {plan.dimension}" if plan.dimension else metric.label


def _empty_message(plan: Plan, filters: Filters, availability: dict[str, Any]) -> str:
    if availability["status"] != "available":
        return availability["reason"]
    return (
        f"No tickets match this plan ({filters.describe()}), so there is nothing to draw: an empty result is not "
        "a zero. Remove a filter or widen the date range."
    )


def _periods(entries: list[dict[str, Any]], plan: Plan, window: tuple[dt.date, dt.date] | None) -> tuple[list[_Group], list[str]]:
    """Every period from the first to the last with a ticket, in date order, a period with none as 0.

    Tickets whose date falls outside the reporting window, or is unusable, are
    kept as their own rows after the periods and never drawn on the axis.
    """
    grouping = TIME_GROUPINGS[plan.dimension]
    basis_label = DATE_BASES[plan.date_basis][1]
    by_key = {entry["key"]: entry for entry in entries}
    starts = sorted(dt.date.fromisoformat(key) for key in by_key if key not in (None, OUTSIDE_WINDOW_KEY))
    groups: list[_Group] = []
    if starts:
        current = starts[0]
        while current <= starts[-1]:
            key = current.isoformat()
            entry = by_key.get(key)
            groups.append(_Group(
                key, key, _period_label(current, grouping), entry["value"] if entry else 0,
                entry["contributing_tickets"] if entry else 0, list(entry.get("excel_rows", [])) if entry else [],
                tick=_period_tick(current, grouping),
            ))
            current = _next_period(current, grouping)
    warnings = []
    outside = by_key.get(OUTSIDE_WINDOW_KEY)
    if outside:
        span = f"{window[0].isoformat()} to {window[1].isoformat()}" if window else "the reporting window"
        rows = list(outside.get("excel_rows", []))
        groups.append(_Group(
            OUTSIDE_ID, OUTSIDE_WINDOW_KEY, f"{basis_label} outside the reporting window ({span})",
            outside["value"], outside["contributing_tickets"], rows,
        ))
        warnings.append(
            f"{outside['contributing_tickets']} ticket{'s' if outside['contributing_tickets'] != 1 else ''} with "
            f"{basis_label} outside the reporting window ({span}) {'are' if len(rows) != 1 else 'is'} listed apart "
            f"from the {plan.dimension.lower()}ly series, dated as recorded and never moved (Excel row"
            f"{'s' if len(rows) != 1 else ''} {_rows_text(rows)}); {'they are' if len(rows) != 1 else 'it is'} "
            "still in the total."
        )
    blank = by_key.get(None)
    if blank:
        rows = list(blank.get("excel_rows", []))
        groups.append(_Group(BLANK_ID, None, f"No usable {basis_label}", blank["value"], blank["contributing_tickets"], rows))
        warnings.append(
            f"{blank['contributing_tickets']} ticket{'s' if blank['contributing_tickets'] != 1 else ''} with no usable "
            f"{basis_label} {'are' if len(rows) != 1 else 'is'} listed apart from the series (Excel row"
            f"{'s' if len(rows) != 1 else ''} {_rows_text(rows)}); still in the total."
        )
    return groups, warnings


def _period_notes(plan: Plan) -> list[str]:
    notes = []
    if TIME_GROUPINGS[plan.dimension] == "week":
        notes.append(
            "A week runs Monday to Sunday and is labelled by its Monday. Every week from the first to the last with "
            "a ticket is shown, a week with none as 0; the first and last weeks can be partial."
        )
    else:
        notes.append(
            "Every month from the first to the last with a ticket is shown, a month with none as 0; the first and "
            "last months can be partial."
        )
    if plan.date_basis == "Created":
        notes.append(
            "Tickets are placed by when they were created, with each ticket's current status: this is not a record "
            "of status changes over time, nor of all company activity."
        )
    return notes


def _period_label(start: dt.date, grouping: str) -> str:
    if grouping == "week":
        return f"Week of {start.day} {start:%b %Y}"
    return f"{start:%B %Y}"


def _period_tick(start: dt.date, grouping: str) -> str:
    return f"{start.day} {start:%b}" if grouping == "week" else f"{start:%b %Y}"


def _next_period(start: dt.date, grouping: str) -> dt.date:
    if grouping == "week":
        return start + dt.timedelta(days=7)
    return (start.replace(day=28) + dt.timedelta(days=4)).replace(day=1)


def _bins(values: dict[int, Any], metric: Metric) -> tuple[list[_Group], Any]:
    """Equal-width, half-open bins [min, max) over the contributing Tickets' values, empty bins included.

    The width is the smallest of 1, 2, 5, 10, 20, 50, ... that keeps the bins
    to MAX_BINS, and the first bin starts at a multiple of it.
    """
    if not values:
        return [], None
    numbers = list(values.values())
    low, high = min(numbers), max(numbers)
    whole = all(isinstance(value, int) for value in numbers)
    width = _bin_width(low, high)
    first = math.floor(low / width)
    count = math.floor(high / width) - first + 1
    rows: list[list[int]] = [[] for _ in range(count)]
    for row, value in sorted(values.items()):
        rows[math.floor(value / width) - first].append(row)
    singular = metric.unit[:-1] if metric.unit.endswith("s") else metric.unit
    groups = []
    for index, members in enumerate(rows):
        start = _plain((first + index) * width)
        end = _plain(start + width)
        if whole and width == 1:
            label = f"{start} {singular if start == 1 else metric.unit}"
        elif whole:
            label = f"{start}–{end - 1} {metric.unit}"
        else:
            label = f"{start} to under {end} {metric.unit}"
        groups.append(_Group(
            f"{start}-{end}", start, label, len(members), len(members), members,
            bin={"min": start, "max": end},
        ))
    return groups, width


def _bin_width(low: Any, high: Any) -> int:
    scale = 1
    while True:
        for step in (1, 2, 5):
            width = step * scale
            if math.floor(high / width) - math.floor(low / width) + 1 <= MAX_BINS:
                return width
        scale *= 10


def _pair(
    evaluated: dict[str, Any], paired: dict[str, Any], values: dict[int, Any], paired_values: dict[int, Any],
) -> tuple[dict[str, Any], list[str], list[dict[str, Any]]]:
    """One point per Ticket with both values known and its labour priced; the rest are reported, never plotted at zero."""
    unpriced = {
        row for item in (paired["coverage"] or {}).get("partial", []) if item["code"] == "unpriced_labour"
        for row in item["excel_rows"]
    }
    plotted = sorted(row for row in values if row in paired_values and row not in unpriced)
    dropped = sorted(row for row in values if row not in set(plotted))
    excluded = list(evaluated["coverage"]["excluded"])
    warnings = list(evaluated["warnings"])
    if dropped:
        message = "labour is unpriced because Rate is missing or not a number, so no base value can be plotted"
        excluded.append({"code": "labour_unpriced", "message": message, "tickets": len(dropped), "excel_rows": dropped})
        warnings.append(
            f"{len(dropped)} ticket{'s' if len(dropped) != 1 else ''} with usable hours {'are' if len(dropped) != 1 else 'is'} "
            f"not plotted because {message} (Excel row{'s' if len(dropped) != 1 else ''} {_rows_text(dropped)}); "
            "they are never plotted at zero."
        )
    coverage = {"contributing_tickets": len(plotted), "excluded": excluded, "partial": []}
    points = [{"excel_row": row, "x": values[row], "y": paired_values[row]} for row in plotted]
    return coverage, warnings, points


def _chart(
    plan: Plan,
    title: str,
    filters: Filters,
    total: Any,
    contributing: int,
    bars: list[Bar],
    shown: list[_Group],
    points: list[dict[str, Any]] | None,
    metric: Metric,
) -> dict[str, Any]:
    """The trusted template's specification for the drawn marks, with the chart's description as accessible name."""
    template = chart_templates.TEMPLATES[plan.chart]
    lead = f"{title}, {filters.describe()}: {template.label.lower()}"
    if plan.form == "pair":
        paired = plan.paired_metric
        description = (
            f"{lead} of {contributing:,} tickets, {metric.label.lower()} ({metric.unit}) across and "
            f"{paired.label.lower()} ({paired.unit}) up, one point per ticket."
        )
        spec = chart_templates.scatter(
            description, f"{metric.label} ({metric.unit})", f"{paired.label} ({paired.unit})",
            [Dot(f"row-{point['excel_row']}", f"Excel row {point['excel_row']}", point["x"], point["y"]) for point in points],
        )
    elif plan.form == "distribution":
        description = f"{lead} of {contributing:,} tickets. " + "; ".join(
            f"{group.label}: {group.value:,}" for group in shown
        ) + "."
        spec = chart_templates.histogram(
            description, f"{metric.label} ({metric.unit})",
            [Bin(group.id, group.label, group.bin["min"], group.bin["max"], group.value) for group in shown],
        )
    elif plan.chart == "line":
        description = f"{lead} of {_total_text(total, contributing, metric)}. " + "; ".join(
            f"{group.label}: {_format(group.value, metric)}" for group in shown
        ) + "."
        spec = chart_templates.line_chart(
            description, f"{plan.dimension} of {DATE_BASES[plan.date_basis][1]}", metric.unit[:1].upper() + metric.unit[1:],
            [Point(group.id, group.label, group.tick, group.value, _format(group.value, metric)) for group in shown],
        )
    else:
        description = f"{lead} of {_total_text(total, contributing, metric)}. " + "; ".join(
            f"{bar.label}: {bar.tip}" for bar in bars
        ) + "."
        category = (
            f"{plan.dimension} of {DATE_BASES[plan.date_basis][1]}" if plan.time_grouping else plan.dimension or "Plan"
        )
        spec = chart_templates.bar_chart(template.id, description, category, metric.unit[:1].upper() + metric.unit[1:], bars)
    return {"template": template.id, "spec": spec}


def _how_calculated(
    plan: Plan, payload: dict[str, Any], inheritance: Inherited, shown: int, rest: int, width: Any,
) -> dict[str, Any]:
    """What the collapsed "How this was calculated" panel shows: formula, exclusions, source rows and the plan."""
    metric = plan.metric
    coverage = payload["coverage"] or {"excluded": [], "partial": []}
    result_block = payload["result"]
    if plan.form == "pair":
        paired = plan.paired_metric
        formula = (
            f"One point per ticket. Across: {metric.label} = {metric.definition} Up: {paired.label} = "
            f"{paired.definition}"
        )
    elif metric.aggregation == DISTRIBUTION:
        formula = (
            f"Each contributing ticket's {metric.label.lower()}, in {metric.unit}: {metric.definition} Tickets are "
            f"counted into equal bins; the median, lowest and highest value are given beside them."
        )
    elif metric.aggregation == "count":
        formula = f"{metric.label} = the number of tickets in scope under the filters. {metric.definition}"
    else:
        formula = (
            f"{metric.label} = the sum, over the contributing tickets, of each ticket's {metric.unit}: "
            f"{metric.definition}"
        )
    exclusions = [{**item, "partial": False} for item in coverage["excluded"]] + [
        {**item, "partial": True} for item in coverage["partial"]
    ]
    return {
        "formula": formula,
        "statistic": metric.statistic,
        "definition": metric.definition,
        "null_treatment": metric.null_treatment,
        "exclusion_rules": list(metric.exclusions_text),
        "exclusions": exclusions,
        "filters": payload["filters"]["description"],
        "starting_filters": inheritance.payload()["label"],
        "date_range": payload["date_range"],
        "presentation": _presentation(plan, payload, shown, rest, width),
        "source_rows": {
            "tickets": payload["lineage"]["contributing_tickets"],
            "excel_rows": payload["lineage"]["contributing_rows"],
        },
        "lineage": metric.lineage,
        "plan": payload["plan"],
        "inherited_filters": payload["inherited_filters"],
        "template": plan.chart,
    }


def _presentation(plan: Plan, payload: dict[str, Any], shown: int, rest: int, width: Any) -> str:
    """How the numbers become marks, in words."""
    form = plan.form
    template = chart_templates.TEMPLATES[plan.chart]
    lead = "No graphic; the table lists every row. " if not template.draws else f"{template.label}. "
    if payload["result"]["empty"]:
        return lead + "Nothing is drawn: no tickets match the plan."
    if form == "pair":
        return lead + "One point per ticket with both values known; both axes start at zero."
    if form == "distribution":
        return lead + (
            f"Tickets counted into {len(payload['result']['groups'])} equal bins of {width} {plan.metric.unit}, each "
            "from its lower edge up to but not including the next; excluded tickets are listed, never binned."
        )
    if form == "dates":
        noun = plan.dimension.lower()
        return lead + (
            f"Every {noun} of {DATE_BASES[plan.date_basis][1]} from the first to the last with a ticket, in date "
            f"order, a {noun} with none as 0; tickets outside the reporting window or with no usable date are rows of "
            "the table, never drawn. The bar limit and Other apply only to categories."
        )
    if form == "total":
        return lead + "One bar for the whole plan; the value axis starts at zero."
    singular, plural = DIMENSION_NOUNS[plan.dimension]
    text = f"{shown} bar{'s' if shown != 1 else ''}, {SORTS[plan.sort].lower()}"
    if rest and plan.include_other:
        text += f"; the other {rest} {singular if rest == 1 else plural} are combined as one Other bar"
    elif rest:
        text += f"; the other {rest} {singular if rest == 1 else plural} are not drawn"
    return lead + text + f". The table lists every {singular}, and the value axis starts at zero."


def drilldown(executed: Executed, group_id: str | None, details: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """The Tickets behind the whole chart or one of its marks, each with its fields and its own value.

    `reproduces` says whether the listing gives back the chart's figure: its
    ticket count for a count, a histogram or a scatterplot, or the sum of the
    listed values for a sum.
    """
    payload = executed.payload
    group, rows, chart_total = drilldown_selection(executed, group_id)
    form = payload["result"]["form"]
    statistic = payload["metric"]["statistic"]
    summed = statistic == "sum" and form not in ("distribution", "pair")
    valued = statistic != "count" or form == "pair"
    listed = []
    for row in rows:
        entry = {**details[row], "value": executed.values.get(row) if valued else None}
        if form == "pair":
            entry["paired_value"] = executed.paired_values.get(row)
        listed.append(entry)
    if valued and form != "pair":
        listed.sort(key=lambda entry: (-(entry["value"] or 0), entry["excel_row"]))
    reproduced = _number_sum(executed.values[row] for row in rows) if summed else len(rows)
    return {
        "plan": payload["plan"],
        "inherited_filters": payload["inherited_filters"],
        "filters": payload["filters"],
        "date_range": payload["date_range"],
        "metric": payload["metric"],
        "paired_metric": payload["paired_metric"],
        "title": payload["title"],
        "grain": payload["grain"],
        "group": group,
        "label": group["label"] if group else "Every ticket in the chart",
        "tickets": len(rows),
        "total": reproduced if rows or chart_total is not None else None,
        "chart_total": chart_total,
        "reproduces": (not rows) if chart_total is None else reproduced == chart_total,
        "value_title": value_title(payload) if valued else None,
        "paired_value_title": (
            f"{payload['paired_metric']['label']} ({payload['paired_metric']['unit']})" if form == "pair" else None
        ),
        "rows": listed,
    }


def drilldown_selection(executed: Executed, group_id: str | None) -> tuple[dict[str, Any] | None, list[int], Any]:
    """The group asked for (None for the whole chart), its Excel rows and the figure the chart shows for it.

    Raises KeyError for a group the result does not hold.
    """
    result_block = executed.payload["result"]
    if group_id is None:
        return None, list(executed.payload["lineage"]["contributing_rows"]), result_block["total"]
    if group_id == OTHER_ID and result_block["other"] is not None:
        other = result_block["other"]
        summary = {key: other[key] for key in ("id", "label", "value", "contributing_tickets")}
        return summary, list(other["excel_rows"]), other["value"]
    for group in result_block["groups"]:
        if group["id"] == group_id:
            summary = {key: group[key] for key in ("id", "label", "value", "contributing_tickets")}
            return summary, list(group["excel_rows"]), group["value"]
    raise KeyError(group_id)


def value_title(payload: dict[str, Any]) -> str:
    metric = payload["metric"]
    return f"{metric['label']} ({metric['unit']})"


def catalogue(fields: tuple[str, ...] | list[str], values: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """What the chips can offer: the allowlisted metrics, fields, operators, charts, sorts and limits, and the starters."""
    return {
        "metrics": [
            {
                "id": metric.id, "label": metric.label, "definition": metric.definition, "unit": metric.unit,
                "statistic": metric.statistic, "allowed_dimensions": list(metric.allowed_dimensions),
                "distribution": metric.aggregation == DISTRIBUTION,
                "availability": metric.availability(fields),
            }
            for metric in EXPLORE_METRICS
        ],
        "fields": [
            {
                "id": name,
                "kind": spec.kind,
                "operators": list(spec.operators),
                "available": name in fields,
                "values": values.get(name, []),
                "nouns": list(DIMENSION_NOUNS[name]),
            }
            for name, spec in TICKET_FIELDS.items()
        ],
        "operators": [{"id": key, "label": label} for key, label in OPERATORS.items()],
        "time_groupings": [
            {"id": name, "label": f"{name} of the date basis", "nouns": list(DIMENSION_NOUNS[name])}
            for name in TIME_GROUPINGS
        ],
        "date_bases": [{"id": key, "label": label, "available": key in fields} for key, (_, label) in DATE_BASES.items()],
        "relative_ranges": [{"id": key, "label": label} for key, label in RELATIVE_RANGES.items()],
        "charts": [
            {"id": template.id, "label": template.label, "forms": list(template.forms)}
            for template in chart_templates.TEMPLATES.values()
        ],
        "scatter_pairs": [
            {"metric_id": key, "paired_metric_id": value, "label": f"{METRICS[key].label} against {METRICS[value].label.lower()}"}
            for key, value in SCATTER_PAIRS.items()
        ],
        "sorts": [{"id": key, "label": label} for key, label in SORTS.items()],
        "ordered_sort": ORDERED_SORT,
        "limits": {"min": MIN_LIMIT, "max": MAX_LIMIT, "default": DEFAULT_LIMIT},
        "max_filters": MAX_FILTERS,
        "starters": [starter.payload() for starter in STARTERS],
    }


@dataclass(frozen=True)
class Starter:
    """A starter question shown as a prefilled chip set (decision-log entry 72)."""

    id: str
    question: str
    plan: dict[str, Any]

    def payload(self) -> dict[str, Any]:
        return {"id": self.id, "question": self.question, "plan": self.plan}


def _starter_plan(metric_id: str, group_by: str, chart: str, filters: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "metric_id": metric_id,
        "group_by": [group_by],
        "filters": filters or [],
        "date_basis": "Created",
        "date_range": None,
        "chart": chart,
        "sort": "metric_desc",
        "limit": DEFAULT_LIMIT,
        "include_other": True,
    }


def _eq(field_name: str, value: Any) -> dict[str, Any]:
    return {"field": field_name, "operator": "eq", "value": value}


# The PRD section 7 example questions that release one's registry metrics answer as bars, and two more from the
# Overview's processing-queue and data-readiness questions.
STARTERS = (
    Starter("tickets_by_status", "Show ticket counts by approval status",
            _starter_plan("ticket_count", "Approval Status", "bar_vertical")),
    Starter("approved_by_keyed", "Show approved tickets split by Keyed status",
            _starter_plan("ticket_count", "Keyed", "bar_vertical", [_eq("Approval Status", "Approved")])),
    Starter("pending_by_supervisor", "Make a bar chart of pending tickets by supervisor",
            _starter_plan("ticket_count", "Supervisor", "bar_horizontal", [_eq("Approval Status", "Pending")])),
    Starter("busiest_jobs", "Show claimed hours for the ten busiest jobs (Approved, Job Number not 0)",
            _starter_plan("claimed_hours", "Job Number", "bar_horizontal", [
                _eq("Approval Status", "Approved"), {"field": "Job Number", "operator": "ne", "value": 0},
            ])),
    Starter("approved_not_keyed_by_supervisor", "Show Approved, not Keyed tickets by supervisor",
            _starter_plan("approved_not_keyed_count", "Supervisor", "bar_horizontal")),
    Starter("missing_rates_by_status", "Show tickets with a missing rate by approval status",
            _starter_plan("missing_rate_count", "Approval Status", "bar_vertical")),
)


def _metric(raw: dict[str, Any], fields: tuple[str, ...] | list[str], issues: list[PlanIssue]) -> Metric | None:
    allowed = [metric.id for metric in EXPLORE_METRICS]
    metric_id = raw["metric_id"]
    metric = METRICS.get(metric_id) if isinstance(metric_id, str) else None
    if metric is None:
        issues.append(PlanIssue(
            "unsupported_metric", "metric_id", f"{metric_id!r} is not a metric in the registry.", allowed,
        ))
        return None
    if metric.grain != "Ticket" or not metric.allowed_dimensions:
        issues.append(PlanIssue(
            "unsupported_metric", "metric_id",
            f"{metric.label} counts {metric.grain.lower()}s rather than tickets and cannot be grouped, so Explore cannot "
            "chart it; the Overview shows it.",
            allowed,
        ))
        return None
    if metric.aggregation not in (*AGGREGATIONS, DISTRIBUTION):
        issues.append(PlanIssue(
            "unsupported_aggregation", "metric_id",
            f"{metric.label} is a {metric.statistic}, which Explore cannot chart; it charts counts, sums and "
            "distributions of one value per ticket.",
            allowed,
        ))
        return None
    availability = metric.availability(fields)
    if availability["status"] != "available":
        issues.append(PlanIssue("metric_unavailable", "metric_id", availability["reason"], allowed))
        return None
    return metric


def _group_by(
    raw: dict[str, Any], metric: Metric | None, fields: tuple[str, ...] | list[str], issues: list[PlanIssue],
) -> tuple[str, ...]:
    group_by = raw["group_by"]
    if not isinstance(group_by, list):
        issues.append(PlanIssue("invalid_plan_value", "group_by", "group_by must be a list of at most one field."))
        return ()
    if len(group_by) > MAX_GROUPINGS:
        issues.append(PlanIssue(
            "too_many_groupings", "group_by", f"A plan can group by at most {MAX_GROUPINGS} field in this release.",
        ))
        return ()
    allowed = [*(metric.allowed_dimensions if metric else TICKET_FIELDS), *TIME_GROUPINGS]
    for index, name in enumerate(group_by):
        path = f"group_by[{index}]"
        if name in TIME_GROUPINGS:
            continue
        if not isinstance(name, str) or name not in SOURCE_COLUMNS:
            issues.append(PlanIssue("unknown_field", path, f"{name!r} is not a column of the export.", allowed))
        elif name not in allowed:
            issues.append(PlanIssue("unsupported_dimension", path, f"Tickets cannot be grouped by {name}.", allowed))
        elif name not in fields:
            issues.append(PlanIssue("field_unavailable", path, f"The workbook has no {name} column to group by."))
    return tuple(group_by)


def _conditions(raw: dict[str, Any], fields: tuple[str, ...] | list[str], issues: list[PlanIssue]) -> tuple[Condition, ...]:
    items = raw["filters"]
    if not isinstance(items, list):
        issues.append(PlanIssue("invalid_plan_value", "filters", "filters must be a list of field conditions."))
        return ()
    if len(items) > MAX_FILTERS:
        issues.append(PlanIssue("too_many_filters", "filters", f"A plan can hold at most {MAX_FILTERS} filters."))
        return ()
    conditions = []
    for index, item in enumerate(items):
        path = f"filters[{index}]"
        if not isinstance(item, dict):
            issues.append(PlanIssue("invalid_plan_value", path, "A filter is an object with field, operator and value."))
            continue
        problems = [
            PlanIssue("unknown_plan_field", f"{path}.{key}", f"{key!r} is not part of a filter.", list(FILTER_KEYS))
            for key in item if key not in FILTER_KEYS
        ] + [
            PlanIssue("missing_plan_field", f"{path}.{key}", f"The filter has no {key}.")
            for key in FILTER_KEYS if key not in item
        ]
        if problems:
            issues.extend(problems)
            continue
        name = item["field"]
        if not isinstance(name, str) or name not in SOURCE_COLUMNS:
            issues.append(PlanIssue(
                "unknown_field", f"{path}.field", f"{name!r} is not a column of the export.", list(TICKET_FIELDS),
            ))
            continue
        operator = item["operator"]
        try:
            conditions.append(Condition.build(name, operator if isinstance(operator, str) else repr(operator), item["value"], fields))
        except FilterError as error:
            issues.append(PlanIssue(error.code, f"{path}.{error.field}", str(error), error.allowed))
    return tuple(conditions)


def _date_basis(raw: dict[str, Any], fields: tuple[str, ...] | list[str], issues: list[PlanIssue]) -> str | None:
    basis = raw["date_basis"]
    if basis not in DATE_BASES:
        issues.append(PlanIssue(
            "unsupported_date_basis", "date_basis", f"{basis!r} is not a date basis.", list(DATE_BASES),
        ))
        return None
    if basis not in fields:
        issues.append(PlanIssue("field_unavailable", "date_basis", f"The workbook has no {basis} column."))
        return None
    return basis


def _date_range(raw: dict[str, Any], issues: list[PlanIssue]) -> tuple[dt.date | None, dt.date | None, str | None]:
    value = raw["date_range"]
    if value is None:
        return None, None, None
    message = (
        'date_range must be null (all dates), {"from": "YYYY-MM-DD" or null, "to": "YYYY-MM-DD" or null}, '
        'or {"relative": one of the relative ranges}.'
    )
    if isinstance(value, dict) and set(value) == {"relative"}:
        relative = value["relative"]
        if not isinstance(relative, str) or relative not in RELATIVE_RANGES:
            issues.append(PlanIssue(
                "invalid_date_range", "date_range",
                f"{relative!r} is not a relative range; it resolves against the as-of date.", list(RELATIVE_RANGES),
            ))
            return None, None, None
        return None, None, relative
    if not isinstance(value, dict) or set(value) - {"from", "to"}:
        issues.append(PlanIssue("invalid_date_range", "date_range", message, list(RELATIVE_RANGES)))
        return None, None, None
    try:
        start, end = _iso_date(value.get("from")), _iso_date(value.get("to"))
    except (TypeError, ValueError):
        issues.append(PlanIssue("invalid_date_range", "date_range", message, list(RELATIVE_RANGES)))
        return None, None, None
    if start is None and end is None:
        issues.append(PlanIssue("invalid_date_range", "date_range", "Give at least one end of the range, or null for all dates."))
    elif start is not None and end is not None and start > end:
        issues.append(PlanIssue("invalid_date_range", "date_range", f"The range starts on {start} after it ends on {end}."))
    return start, end, None


def _choice(
    raw: dict[str, Any], key: str, allowed: dict[str, Any], code: str, noun: str, issues: list[PlanIssue],
) -> Any:
    if key not in raw:
        return None
    value = raw[key]
    if not isinstance(value, str) or value not in allowed:
        issues.append(PlanIssue(code, key, f"{value!r} is not a supported {noun}.", list(allowed)))
        return None
    return value


def _limit(raw: dict[str, Any], issues: list[PlanIssue]) -> int | None:
    limit = raw["limit"]
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < MIN_LIMIT:
        issues.append(PlanIssue(
            "invalid_limit", "limit", f"limit must be a whole number of bars from {MIN_LIMIT} to {MAX_LIMIT}.",
        ))
        return None
    if limit > MAX_LIMIT:
        issues.append(PlanIssue(
            "limit_too_large", "limit",
            f"A chart draws at most {MAX_LIMIT} bars; the table always lists every group. Choose {MAX_LIMIT} or fewer.",
        ))
        return None
    return limit


def _iso_date(value: Any) -> dt.date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{value!r} is not an ISO date")
    return dt.date.fromisoformat(value)


def _group_id(key: Any) -> str:
    if key is None:
        return BLANK_ID
    if isinstance(key, bool):
        return "true" if key else "false"
    return str(key)


def group_label(dimension: str, key: Any, job_names: dict[int, str | None]) -> str:
    """A group's category as shown: a Job Number with its usual Job Name, true or false, or the value as recorded."""
    if key is None:
        return BLANK_LABEL
    if isinstance(key, bool):
        return "true" if key else "false"
    if dimension == "Job Number" and job_names.get(key):
        return f"{key} {job_names[key]}"
    return str(key)


def _sorted(groups: list[_Group], sort: str, dimension: str | None) -> list[_Group]:
    """Groups in the plan's order; equal values fall back to A to Z, and the blank group always comes last among equals."""

    def label_key(group: _Group) -> tuple:
        if group.key is None:
            return (1, 0, "")
        if dimension in ("Job Number", "Keyed"):
            return (0, int(group.key), "")
        return (0, 0, group.label.casefold())

    if sort == "metric_desc":
        return sorted(groups, key=lambda group: (-group.value, label_key(group)))
    if sort == "metric_asc":
        return sorted(groups, key=lambda group: (group.value, label_key(group)))
    return sorted(groups, key=label_key)


def _tie_warning(plan: Plan, shown: list[_Group], rest: list[_Group]) -> list[str]:
    """Say so when equal values straddle the last bar, so a bar of its own is never read as a ranking."""
    if not shown or not rest or plan.sort == "label_asc" or rest[0].value != shown[-1].value:
        return []
    tied_shown = sum(1 for group in shown if group.value == shown[-1].value)
    tied_rest = sum(1 for group in rest if group.value == shown[-1].value)
    singular, plural = DIMENSION_NOUNS[plan.dimension]
    where = "in Other" if plan.include_other else "left out of the chart"
    return [
        f"{tied_shown + tied_rest} {plural} have the same value as the last bar ({_format(shown[-1].value, plan.metric)}): "
        f"{tied_shown} {'is' if tied_shown == 1 else 'are'} drawn and {tied_rest} {where}, in A to Z order. "
        "Which of them gets a bar is not a ranking."
    ]


def _summary(plan: Plan, filters: Filters, metric: Metric, groups: int, rest: int, width: Any) -> str:
    """The plan in one plain sentence, built from its fields (no model writes it)."""
    if plan.form == "pair":
        paired = plan.paired_metric
        return (
            f"{metric.label} against {paired.label.lower()}: one point per ticket, {metric.unit} across and "
            f"{paired.unit} up; {filters.describe()}."
        )
    if plan.form == "distribution":
        sentence = f"{metric.label}: how many tickets fall in each range of {metric.unit}"
        if width is not None:
            sentence += f", in bins of {width} {metric.unit}"
        return sentence + f"; {filters.describe()}."
    sentence = f"{metric.label}: the {metric.statistic} of {metric.unit}"
    if plan.time_grouping:
        noun = plan.dimension.lower()
        return sentence + (
            f", by {noun} of {DATE_BASES[plan.date_basis][1]}; {filters.describe()}. Every {noun} is drawn in date "
            "order; the bar limit and Other apply only to categories."
        )
    if plan.dimension:
        sentence += f", by {plan.dimension}"
    sentence += f"; {filters.describe()}."
    if plan.dimension and rest:
        singular, plural = DIMENSION_NOUNS[plan.dimension]
        if plan.include_other:
            sentence += (
                f" {plan.limit} bars are drawn and the other {rest} {singular if rest == 1 else plural} are combined "
                f"as Other; the table lists all {groups}."
            )
        else:
            sentence += f" {plan.limit} bars are drawn; the table lists all {groups} {plural}."
    return sentence


def _plain(value: Any) -> Any:
    """A whole float as an int, so bin edges read 2 rather than 2.0."""
    return int(value) if isinstance(value, float) and value.is_integer() else value


def _number_sum(values) -> Any:
    total = sum(values)
    if isinstance(total, float):
        total = round(total, 4)
        return int(total) if total.is_integer() else total
    return total


def _format(value: Any, metric: Metric) -> str:
    if value is None:
        return "no value"
    if metric.unit == "BBD":
        return f"{value:,.2f}"
    if isinstance(value, float) and not value.is_integer():
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    return f"{int(value):,}"


def _total_text(total: Any, contributing: int, metric: Metric) -> str:
    if metric.aggregation == "count":
        return f"{_format(total, metric)} {metric.unit}"
    return f"{_format(total, metric)} {metric.unit} over {contributing:,} tickets"
