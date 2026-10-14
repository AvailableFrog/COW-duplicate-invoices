"""The global filter state: date basis and range, job and status.

Filters narrow the Tickets every metric counts. With no date range a metric
covers all dates, so totals reconcile with the import; a date range always
names the date basis it applies to. A Ticket whose filtered value is unusable
(an invalid status, a missing date on the chosen basis) falls outside an
active filter rather than being guessed into it.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from labour_ticket_analytics.validation import APPROVAL_STATUSES

# Date basis ID (the source column) -> (normalized column, label).
DATE_BASES: dict[str, tuple[str, str]] = {
    "Created": ("created", "Created"),
    "Date": ("work_date", "Date as recorded"),
    "Date Approved": ("date_approved", "Date Approved"),
}
DEFAULT_DATE_BASIS = "Created"


class FilterError(ValueError):
    """A filter value outside the allowlist; field names the offending filter."""

    def __init__(self, field_name: str, message: str) -> None:
        super().__init__(message)
        self.field = field_name

    def payload(self) -> dict[str, str]:
        return {"code": "invalid_filter", "field": self.field, "message": str(self)}


@dataclass(frozen=True)
class Filters:
    date_basis: str = DEFAULT_DATE_BASIS
    date_from: dt.date | None = None
    date_to: dt.date | None = None
    jobs: tuple[int, ...] = ()
    statuses: tuple[str, ...] = ()

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
        )

    @property
    def has_date_range(self) -> bool:
        return self.date_from is not None or self.date_to is not None

    @property
    def active(self) -> bool:
        return self.has_date_range or bool(self.jobs) or bool(self.statuses)

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
        return "; ".join(parts)
