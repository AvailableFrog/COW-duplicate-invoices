"""Explore query plans (PRD section 7): validate, compile and shape the result of a typed plan.

A plan names what to chart, never how to compute it: a registry metric, at
most one grouping dimension, field conditions, a date basis and range, a
chart template, a sort, a bar limit and whether the rest are combined as
Other. Its nine fields are all required, so nothing is assumed silently.
`validate` checks every one against an allowlist and reports every problem
at once as a structured, recoverable issue naming the field at fault and,
where it helps, the values that are allowed. `compile` turns a valid plan
and any inherited Overview filters into the registry's Filters, whose SQL is
parameterized and executed by `metrics.evaluate` inside a read-only
transaction (store.evaluate_plan); a plan never carries SQL, a column name
outside the allowlist or a chart specification. `result` shapes the
evaluated metric into bars, the full table, lineage and a trusted chart
template (chart_templates.py).

The Snapshot fingerprint, the as-of date, the versions and the inherited
filters are attached to every response beside the plan, never inside it,
so neither the chips nor a release-two provider can change them.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from labour_ticket_analytics import chart_templates
from labour_ticket_analytics.chart_templates import Bar
from labour_ticket_analytics.filters import (
    DATE_BASES, DEFAULT_DATE_BASIS, OPERATORS, TICKET_FIELDS, Condition, FilterError, Filters,
)
from labour_ticket_analytics.metrics import METRICS, REGISTRY, Metric
from labour_ticket_analytics.schema import OPTIONAL_COLUMNS, REQUIRED_COLUMNS

PLAN_FIELDS = (
    "metric_id", "group_by", "filters", "date_basis", "date_range", "chart", "sort", "limit", "include_other",
)
FILTER_KEYS = ("field", "operator", "value")
# Only additive statistics: a group's share of Other is then exactly the sum of the groups it holds.
AGGREGATIONS = ("count", "sum")
SORTS: dict[str, str] = {"metric_desc": "Largest first", "metric_asc": "Smallest first", "label_asc": "A to Z"}
MIN_LIMIT, MAX_LIMIT, DEFAULT_LIMIT = 1, 25, 10
MAX_GROUPINGS = 1
MAX_FILTERS = 10
SOURCE_COLUMNS = (*REQUIRED_COLUMNS, *OPTIONAL_COLUMNS)

BLANK_ID = "__blank__"
BLANK_LABEL = "Blank or unreadable"
OTHER_ID = "__other__"
TOTAL_ID = "__total__"

# How a grouping's categories are counted in words: one and many.
DIMENSION_NOUNS: dict[str, tuple[str, str]] = {
    "Approval Status": ("status", "statuses"),
    "Keyed": ("Keyed value", "Keyed values"),
    "Job Number": ("job", "jobs"),
    "Job Name": ("job name", "job names"),
    "Supervisor": ("supervisor", "supervisors"),
    "Occupation": ("occupation", "occupations"),
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

    @property
    def metric(self) -> Metric:
        return METRICS[self.metric_id]

    @property
    def dimension(self) -> str | None:
        return self.group_by[0] if self.group_by else None

    @property
    def has_date_range(self) -> bool:
        return self.date_from is not None or self.date_to is not None

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
    """A registry metric Explore can draw as bars: counted per Ticket, additive and groupable."""
    return metric.grain == "Ticket" and metric.aggregation in AGGREGATIONS and bool(metric.allowed_dimensions)


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
    date_from, date_to = _date_range(raw, issues) if "date_range" in raw else (None, None)
    chart = _choice(raw, "chart", chart_templates.TEMPLATES, "unsupported_chart", "chart", issues)
    sort = _choice(raw, "sort", SORTS, "unsupported_sort", "sort", issues)
    limit = _limit(raw, issues) if "limit" in raw else None
    include_other = raw.get("include_other")
    if "include_other" in raw and not isinstance(include_other, bool):
        issues.append(PlanIssue("invalid_plan_value", "include_other", "include_other must be true or false."))

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
    )


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


def compile_filters(plan: Plan, inheritance: Inherited, fields: tuple[str, ...] | list[str]) -> Filters:
    """The registry Filters a plan runs under: its conditions and date range, and the inherited jobs, statuses and range.

    Two date ranges are never combined or one silently dropped: a plan with
    its own range under Overview filters that also hold one is refused.
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

    def payload(self) -> dict[str, Any]:
        return {
            "id": self.id, "key": self.key, "label": self.label, "value": self.value,
            "contributing_tickets": self.contributing_tickets, "excel_rows": self.excel_rows,
            "shown": self.shown, "in_other": self.in_other,
        }


def result(
    plan: Plan,
    inheritance: Inherited,
    filters: Filters,
    evaluated: dict[str, Any],
    job_names: dict[int, str | None],
) -> dict[str, Any]:
    """The executed plan: bars (top N and Other), the full table, lineage, warnings and the chart specification."""
    metric = plan.metric
    dimension = plan.dimension
    available = evaluated["availability"]["status"] == "available"
    if dimension is None:
        groups = [] if not available or not evaluated["coverage"]["contributing_tickets"] else [_Group(
            TOTAL_ID, None, "All tickets in the plan", evaluated["value"],
            evaluated["coverage"]["contributing_tickets"], list(evaluated.get("contributing_rows", [])),
        )]
    else:
        groups = [
            _Group(
                _group_id(entry["key"]), entry["key"], group_label(dimension, entry["key"], job_names),
                entry["value"], entry["contributing_tickets"], list(entry.get("excel_rows", [])),
            )
            for entry in evaluated["groups"] or []
        ]
    groups = _sorted(groups, plan.sort, dimension)
    shown, rest = groups[:plan.limit], groups[plan.limit:]
    for group in shown:
        group.shown = True
    other = None
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

    warnings = list(evaluated["warnings"])
    warnings.extend(_tie_warning(plan, shown, rest))
    parent = inheritance.filters
    if parent is not None and parent.has_date_range and parent.date_basis != plan.date_basis:
        warnings.append(
            f"The Overview filters' date range applies to {DATE_BASES[parent.date_basis][1]}; the plan's date basis, "
            f"{DATE_BASES[plan.date_basis][1]}, has no range of its own."
        )
    notes = [DIMENSION_NOTES[dimension]] if dimension in DIMENSION_NOTES else []

    contributing = evaluated["coverage"]["contributing_tickets"] if evaluated["coverage"] else 0
    title = f"{metric.label} by {dimension}" if dimension else metric.label
    value_title = metric.unit[:1].upper() + metric.unit[1:]
    total = evaluated["value"] if available else None
    empty = not bars
    chart = None
    if not empty:
        template = chart_templates.TEMPLATES[plan.chart]
        description = (
            f"{title}, {filters.describe()}: {template.label.lower()} of {_total_text(total, contributing, metric)}. "
            + "; ".join(f"{bar.label}: {bar.tip}" for bar in bars) + "."
        )
        chart = {
            "template": template.id,
            "spec": chart_templates.bar_chart(template.id, description, dimension or "Plan", value_title, bars),
        }
    return {
        "plan": plan.payload(),
        "inherited_filters": inheritance.payload(),
        "filters": filters.payload(),
        "metric": {
            "id": metric.id, "label": metric.label, "definition": metric.definition, "unit": metric.unit,
            "statistic": metric.statistic,
        },
        "availability": evaluated["availability"],
        "title": title,
        "summary": _summary(plan, filters, metric, len(groups), len(rest)),
        "grain": metric.grain,
        "result": {
            "total": total,
            "contributing_tickets": contributing,
            "unit": metric.unit,
            "value_title": value_title,
            "empty": empty,
            "groups": [group.payload() for group in groups],
            "bars": [{"id": bar.id, "label": bar.label, "value": bar.value, "other": bar.other} for bar in bars],
            "other": other,
            "hidden_groups": 0 if plan.include_other else len(rest),
            "percentage": evaluated.get("percentage"),
        },
        "chart": chart,
        "lineage": {
            "metric_id": metric.id,
            "metric": metric.lineage,
            "contributing_tickets": contributing,
            "contributing_rows": list(evaluated.get("contributing_rows", [])),
        },
        "coverage": evaluated["coverage"],
        "warnings": warnings,
        "notes": notes,
    }


def catalogue(fields: tuple[str, ...] | list[str], values: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """What the chips can offer: the allowlisted metrics, fields, operators, charts, sorts and limits, and the starters."""
    return {
        "metrics": [
            {
                "id": metric.id, "label": metric.label, "definition": metric.definition, "unit": metric.unit,
                "statistic": metric.statistic, "allowed_dimensions": list(metric.allowed_dimensions),
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
        "date_bases": [{"id": key, "label": label, "available": key in fields} for key, (_, label) in DATE_BASES.items()],
        "charts": [{"id": template.id, "label": template.label} for template in chart_templates.TEMPLATES.values()],
        "sorts": [{"id": key, "label": label} for key, label in SORTS.items()],
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
    if metric.aggregation not in AGGREGATIONS:
        issues.append(PlanIssue(
            "unsupported_aggregation", "metric_id",
            f"{metric.label} is a {metric.statistic} over tickets, which cannot be split into bars and an Other bar; "
            "Explore charts counts and sums. Choose a count or sum metric.",
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
    allowed = list(metric.allowed_dimensions) if metric else list(TICKET_FIELDS)
    for index, name in enumerate(group_by):
        path = f"group_by[{index}]"
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


def _date_range(raw: dict[str, Any], issues: list[PlanIssue]) -> tuple[dt.date | None, dt.date | None]:
    value = raw["date_range"]
    if value is None:
        return None, None
    message = 'date_range must be null (all dates) or {"from": "YYYY-MM-DD" or null, "to": "YYYY-MM-DD" or null}.'
    if not isinstance(value, dict) or set(value) - {"from", "to"}:
        issues.append(PlanIssue("invalid_date_range", "date_range", message))
        return None, None
    try:
        start, end = _iso_date(value.get("from")), _iso_date(value.get("to"))
    except (TypeError, ValueError):
        issues.append(PlanIssue("invalid_date_range", "date_range", message))
        return None, None
    if start is None and end is None:
        issues.append(PlanIssue("invalid_date_range", "date_range", "Give at least one end of the range, or null for all dates."))
    elif start is not None and end is not None and start > end:
        issues.append(PlanIssue("invalid_date_range", "date_range", f"The range starts on {start} after it ends on {end}."))
    return start, end


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


def _summary(plan: Plan, filters: Filters, metric: Metric, groups: int, rest: int) -> str:
    """The plan in one plain sentence, built from its fields (no model writes it)."""
    sentence = f"{metric.label}: the {metric.statistic} of {metric.unit}"
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
