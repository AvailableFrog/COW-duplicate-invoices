"""The filter state: date basis and range, job and status, and field conditions.

Filters narrow the Tickets every metric counts. With no date range a metric
covers all dates, so totals reconcile with the import; a date range always
names the date basis it applies to. A Ticket whose filtered value is unusable
(an invalid status, a missing date on the chosen basis, a blank supervisor)
falls outside an active filter rather than being guessed into it, whatever
the operator: "is not 0" never matches a Job Number that is not a number.

The global filter bar sets the date range, jobs and statuses. An Explore plan
adds conditions on the Ticket fields in TICKET_FIELDS, each with an operator
from that field's allowlist; values always travel as query parameters and
only allowlisted column names reach the SQL.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Literal

from labour_ticket_analytics.validation import APPROVAL_STATUSES

# Date basis ID (the source column) -> (normalized column, label).
DATE_BASES: dict[str, tuple[str, str]] = {
    "Created": ("created", "Created"),
    "Date": ("work_date", "Date as recorded"),
    "Date Approved": ("date_approved", "Date Approved"),
}
DEFAULT_DATE_BASIS = "Created"

# Operator ID -> how a condition reads on screen.
OPERATORS: dict[str, str] = {"eq": "is", "ne": "is not", "in": "is one of", "not_in": "is none of"}
LIST_OPERATORS = ("in", "not_in")
# The most values one "is one of" condition may list.
MAX_CONDITION_VALUES = 50
# Bounds on one condition value: a Job Number fits the stored BIGINT, and text is a recorded label, not a document.
MAX_INTEGER = 2**63 - 1
MAX_TEXT_LENGTH = 200


@dataclass(frozen=True)
class TicketField:
    """A source column the registry can group and filter by: its normalized column, value kind and operators."""

    column: str
    kind: Literal["status", "boolean", "integer", "text"]
    operators: tuple[str, ...]


_ALL = ("eq", "ne", "in", "not_in")
# The Ticket fields metrics are grouped and filtered by; metrics.DIMENSIONS is this map's columns.
TICKET_FIELDS: dict[str, TicketField] = {
    "Approval Status": TicketField("status", "status", _ALL),
    "Keyed": TicketField("keyed", "boolean", ("eq", "ne")),
    "Job Number": TicketField("job_number", "integer", _ALL),
    "Job Name": TicketField("job_name", "text", _ALL),
    "Supervisor": TicketField("supervisor", "text", _ALL),
    "Occupation": TicketField("occupation", "text", _ALL),
}


class FilterError(ValueError):
    """A filter value outside the allowlist; field names the offending filter and code says how it failed."""

    def __init__(self, field_name: str, message: str, code: str = "invalid_filter", allowed: list | None = None) -> None:
        super().__init__(message)
        self.field = field_name
        self.code = code
        self.allowed = allowed

    def payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "field": self.field, "message": str(self)}
        if self.allowed is not None:
            payload["allowed"] = self.allowed
        return payload


@dataclass(frozen=True)
class Condition:
    """One field condition: a Ticket field from TICKET_FIELDS, an allowlisted operator and its values."""

    field: str
    operator: str
    values: tuple[Any, ...]

    @classmethod
    def build(cls, field_name: str, operator: str, value: Any, fields: tuple[str, ...] | list[str]) -> Condition:
        """A validated condition for a Snapshot with these source fields; raises FilterError naming the part at fault."""
        spec = TICKET_FIELDS.get(field_name)
        if spec is None:
            raise FilterError(
                "field", f"{field_name!r} cannot be filtered on", "unsupported_filter_field", list(TICKET_FIELDS),
            )
        if field_name not in fields:
            raise FilterError("field", f"the workbook has no {field_name} column to filter on", "field_unavailable")
        if operator not in spec.operators:
            raise FilterError(
                "operator", f"{field_name} cannot be filtered with {operator!r}; allowed: {', '.join(spec.operators)}",
                "unsupported_operator", list(spec.operators),
            )
        if operator in LIST_OPERATORS:
            if not isinstance(value, list) or not value:
                raise FilterError("value", f"{OPERATORS[operator]!r} needs a list of values", "invalid_filter_value")
            if len(value) > MAX_CONDITION_VALUES:
                raise FilterError(
                    "value", f"a condition may list at most {MAX_CONDITION_VALUES} values", "invalid_filter_value",
                )
            values = value
        else:
            if isinstance(value, list):
                raise FilterError("value", f"{OPERATORS[operator]!r} takes one value, not a list", "invalid_filter_value")
            values = [value]
        for item in values:
            _check_value(field_name, spec, item)
        unique = tuple(dict.fromkeys(values))
        return cls(field=field_name, operator=operator, values=unique)

    @property
    def value(self) -> Any:
        """The condition's value as a plan writes it: one value, or a list for "is one of"."""
        return list(self.values) if self.operator in LIST_OPERATORS else self.values[0]

    def sql(self, alias: str, parameter: str) -> str:
        """A predicate that is false (never unknown) for a Ticket whose value is unusable."""
        column = f"{alias}.{TICKET_FIELDS[self.field].column}"
        if self.operator == "eq":
            predicate = f"{column} = ${parameter}"
        elif self.operator == "ne":
            predicate = f"{column} <> ${parameter}"
        elif self.operator == "in":
            predicate = f"list_contains(${parameter}, {column})"
        else:
            predicate = f"NOT list_contains(${parameter}, {column})"
        return f"COALESCE({column} IS NOT NULL AND {predicate}, false)"

    def payload(self) -> dict[str, Any]:
        return {"field": self.field, "operator": self.operator, "value": self.value, "description": self.describe()}

    def describe(self) -> str:
        shown = ", ".join(_display(item) for item in self.values)
        return f"{self.field} {OPERATORS[self.operator]} {shown}"


def _check_value(field_name: str, spec: TicketField, value: Any) -> None:
    if spec.kind == "boolean":
        ok = isinstance(value, bool)
        expected = "true or false"
    elif spec.kind == "integer":
        ok = isinstance(value, int) and not isinstance(value, bool) and -MAX_INTEGER <= value <= MAX_INTEGER
        expected = "a whole number"
    elif spec.kind == "status":
        ok = value in APPROVAL_STATUSES
        expected = f"one of {', '.join(APPROVAL_STATUSES)}"
    else:
        ok = isinstance(value, str) and bool(value.strip()) and len(value) <= MAX_TEXT_LENGTH
        expected = f"nonblank text of at most {MAX_TEXT_LENGTH} characters"
    if not ok:
        raise FilterError(
            "value", f"{field_name} values must be {expected}, not {value!r}", "invalid_filter_value",
            list(APPROVAL_STATUSES) if spec.kind == "status" else None,
        )


def _display(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


@dataclass(frozen=True)
class Filters:
    date_basis: str = DEFAULT_DATE_BASIS
    date_from: dt.date | None = None
    date_to: dt.date | None = None
    jobs: tuple[int, ...] = ()
    statuses: tuple[str, ...] = ()
    conditions: tuple[Condition, ...] = ()

    @classmethod
    def build(
        cls,
        *,
        fields: tuple[str, ...] | list[str],
        date_basis: str = DEFAULT_DATE_BASIS,
        date_from: dt.date | None = None,
        date_to: dt.date | None = None,
        jobs: list[int] | tuple[int, ...] = (),
        statuses: list[str] | tuple[str, ...] = (),
        conditions: tuple[Condition, ...] = (),
    ) -> Filters:
        """Validated filters for a Snapshot with these source fields; raises FilterError."""
        if date_basis not in DATE_BASES:
            raise FilterError("date_basis", f"date basis must be one of {', '.join(DATE_BASES)}, not {date_basis!r}")
        if date_basis not in fields:
            raise FilterError("date_basis", f"the workbook has no {date_basis} column, so it cannot be a date basis")
        if date_from is not None and date_to is not None and date_from > date_to:
            raise FilterError("date_range", f"the range starts on {date_from} after it ends on {date_to}")
        for status in statuses:
            if status not in APPROVAL_STATUSES:
                raise FilterError("status", f"status must be one of {', '.join(APPROVAL_STATUSES)}, not {status!r}")
        return cls(
            date_basis=date_basis,
            date_from=date_from,
            date_to=date_to,
            jobs=tuple(sorted(set(jobs))),
            statuses=tuple(status for status in APPROVAL_STATUSES if status in statuses),
            conditions=tuple(conditions),
        )

    @property
    def has_date_range(self) -> bool:
        return self.date_from is not None or self.date_to is not None

    @property
    def active(self) -> bool:
        return self.has_date_range or bool(self.jobs) or bool(self.statuses) or bool(self.conditions)

    def sql(self, alias: str = "t") -> tuple[str, dict[str, Any]]:
        """A WHERE fragment over normalized Ticket values and its named parameters."""
        clauses: list[str] = []
        parameters: dict[str, Any] = {}
        column = f"{alias}.{DATE_BASES[self.date_basis][0]}"
        if self.date_from is not None:
            clauses.append(f"CAST({column} AS DATE) >= $date_from")
            parameters["date_from"] = self.date_from
        if self.date_to is not None:
            clauses.append(f"CAST({column} AS DATE) <= $date_to")
            parameters["date_to"] = self.date_to
        if self.jobs:
            clauses.append(f"list_contains($jobs, {alias}.job_number)")
            parameters["jobs"] = list(self.jobs)
        if self.statuses:
            clauses.append(f"list_contains($statuses, {alias}.status)")
            parameters["statuses"] = list(self.statuses)
        for index, condition in enumerate(self.conditions):
            name = f"condition_{index}"
            clauses.append(condition.sql(alias, name))
            parameters[name] = condition.value
        return (" AND ".join(clauses) or "TRUE"), parameters

    def payload(self) -> dict[str, Any]:
        """The filter state as every view displays it."""
        date_range = None
        if self.has_date_range:
            date_range = {
                "from": self.date_from.isoformat() if self.date_from else None,
                "to": self.date_to.isoformat() if self.date_to else None,
            }
        return {
            "date_basis": {"id": self.date_basis, "label": DATE_BASES[self.date_basis][1]},
            "date_range": date_range,
            "jobs": list(self.jobs),
            "statuses": list(self.statuses),
            "conditions": [condition.payload() for condition in self.conditions],
            "active": self.active,
            "description": self.describe(),
        }

    def describe(self) -> str:
        parts: list[str] = []
        label = DATE_BASES[self.date_basis][1]
        if self.has_date_range:
            start = self.date_from.isoformat() if self.date_from else "the earliest date"
            end = self.date_to.isoformat() if self.date_to else "the latest date"
            parts.append(f"{label} from {start} to {end}")
        else:
            parts.append("all dates")
        if self.jobs:
            parts.append(f"Job Number {', '.join(str(job) for job in self.jobs)}")
        if self.statuses:
            parts.append(f"Approval Status {', '.join(self.statuses)}")
        parts.extend(condition.describe() for condition in self.conditions)
        return "; ".join(parts)
