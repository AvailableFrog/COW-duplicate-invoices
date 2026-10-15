"""The Data readiness view: which records cannot be reliably compared or valued (PRD section 4).

Six compact counts, each drilling down to exactly the rows it counts: Tickets
with an Ambiguous Interval, Tickets with a date outside the reporting window,
Tickets whose description names a date that differs from Date, proposed
Aliases nobody has decided, Tickets with no usable Rate, and Tickets with an
empty required cell. Every Ticket count is a registry metric under the global
filters; the Alias count reads the Name-space variant's proposals and the local
review file (decision-log entries 69-71).

Nothing here corrects a value: an out-of-window date is shown as recorded and
no year is reassigned, a description never changes Date, and a missing Rate is
never valued at zero. The counts overlap and are never added together.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Callable

from labour_ticket_analytics.filters import FilterError

TITLE = "Data readiness"
QUESTION = "Which records cannot be reliably compared or valued?"
NOTE = (
    "Each count lists exactly the records it counts. The counts overlap, since one ticket can need several checks, "
    "so they are never added together. Nothing is corrected: dates are shown as recorded, no year is reassigned, "
    "a description never changes Date and a missing Rate is never valued at zero."
)
WINDOW_NOTE = (
    "Dates outside this window are shown separately, as recorded; none is corrected or moved to another year. "
    "The default covers the years of Created."
)


@dataclass(frozen=True)
class Check:
    """One readiness count: what it asks, and the registry metric that counts it (None for the Alias proposals)."""

    id: str
    label: str
    metric_id: str | None
    unit: str
    grain: str
    description: str

    def payload(self) -> dict[str, Any]:
        return {
            "id": self.id, "label": self.label, "metric_id": self.metric_id, "unit": self.unit, "grain": self.grain,
            "description": self.description,
        }


CHECKS: tuple[Check, ...] = (
    Check(
        "ambiguous_intervals", "Ambiguous times", "ambiguous_interval_ticket_count", "tickets", "Ticket",
        "Time has a work period without AM/PM: shown with an assumed reading, never used to prove overlap.",
    ),
    Check(
        "anomalous_dates", "Dates outside the reporting window", "anomalous_date_count", "tickets", "Ticket",
        "Date, Created or Date Approved falls outside the reporting window; shown as recorded, never reassigned.",
    ),
    Check(
        "description_date_conflicts", "Date conflicts in descriptions", "description_date_conflict_count", "tickets",
        "Ticket",
        "The description names a date that differs from Date. Date is kept; this never links tickets.",
    ),
    Check(
        "unresolved_identity", "Unresolved name proposals", None, "proposed Aliases", "Proposed Alias",
        "Two employee names proposed as one person, with no decision yet. Confirm or reject each in its possible "
        "duplicate.",
    ),
    Check(
        "missing_rates", "Missing rates", "missing_rate_count", "tickets", "Ticket",
        "Rate is blank or not a number, so claimed labour cannot be priced; it is never valued at zero.",
    ),
    Check(
        "missing_required_fields", "Missing required fields", "missing_required_field_count", "tickets", "Ticket",
        "A required cell is empty, from the import issues. The ticket stays and nothing is filled in.",
    ),
)
CHECK_BY_ID = {check.id: check for check in CHECKS}

UNRESOLVED_IDENTITY_DEFINITION = (
    "Aliases the Name-space variant proposes (two employee names equal once spaces and case are ignored, on the same "
    "claim) that no reviewer has confirmed or rejected. One proposal counts once however many ticket pairs propose "
    "it, and is inside the filters when any of those tickets is. A shared email is never a reason."
)


@dataclass(frozen=True)
class ReportingWindow:
    """The visible, configurable date range readiness compares dates with, both ends inclusive."""

    date_from: dt.date
    date_to: dt.date
    default: tuple[dt.date, dt.date] | None

    @classmethod
    def build(
        cls, default: tuple[dt.date, dt.date] | None, date_from: dt.date | None, date_to: dt.date | None,
    ) -> ReportingWindow | None:
        """The window asked for, either end defaulting to the Created years; None when neither is known.

        Raises FilterError (field `reporting_window`) for a window that ends before it starts.
        """
        start = date_from or (default[0] if default else None)
        end = date_to or (default[1] if default else None)
        if start is None or end is None:
            return None
        if start > end:
            raise FilterError("reporting_window", f"the reporting window starts on {start} after it ends on {end}")
        return cls(start, end, default)

    @property
    def bounds(self) -> tuple[dt.date, dt.date]:
        return self.date_from, self.date_to

    def payload(self) -> dict[str, Any]:
        default = self.default
        return {
            "from": self.date_from.isoformat(),
            "to": self.date_to.isoformat(),
            "default_from": default[0].isoformat() if default else None,
            "default_to": default[1].isoformat() if default else None,
            "is_default": default is not None and self.bounds == default,
            "dates_checked": ["Date", "Created", "Date Approved"],
            "description": f"{_spoken(self.date_from)} to {_spoken(self.date_to)}",
            "note": WINDOW_NOTE,
        }


def unresolved_aliases(aliases: list[dict[str, Any]], inside: dict[int, bool]) -> list[dict[str, Any]]:
    """Proposed Aliases with no decision, any of whose proposing Tickets is inside the filters, by label pair."""
    return [
        alias for alias in aliases
        if alias["decision"]["id"] == "proposed"
        and any(inside.get(row, False) for pair in alias["proposed_by"] for row in pair)
    ]


def summary_item(check: Check, result: dict[str, Any] | None, count: int | None, extra: str | None) -> dict[str, Any]:
    """One count as the view shows it: the check, its value, definition, availability and warnings."""
    if result is None:  # the Alias proposals: not a Ticket metric
        return {
            **check.payload(), "count": count, "definition": UNRESOLVED_IDENTITY_DEFINITION,
            "availability": {"status": "available", "reason": None}, "summary": extra, "warnings": [],
        }
    return {
        **check.payload(),
        "count": result["value"],
        "definition": result["metric"]["definition"],
        "availability": result["availability"],
        "summary": extra,
        "warnings": result["warnings"],
    }


def ticket_row(check: Check, ticket: dict[str, Any], window: ReportingWindow | None) -> dict[str, Any]:
    """One drilldown row: the Ticket's identity and source state, and what this check found on it."""
    row = {
        key: ticket[key]
        for key in ("excel_row", "ticket_number", "employee", "date", "created", "status", "keyed", "in_filter")
    }
    if check.id == "ambiguous_intervals":
        parse = ticket["time_parse"]
        row["detail"] = {
            "time": parse["raw_time"]["value"],
            "status": parse["status"],
            "ambiguous_periods": [
                {"text": period["text"], "plausible_reading": period["plausible_reading"], "flags": period["flags"]}
                for period in parse["periods"] if period["confidence"] == "ambiguous"
            ],
        }
    elif check.id == "anomalous_dates":
        assert window is not None
        row["detail"] = {
            "outside": [
                {"field": field, "value": value}
                for field, value in ticket["dates"].items()
                if value is not None and not window.date_from <= dt.date.fromisoformat(value) <= window.date_to
            ],
        }
    elif check.id == "description_date_conflicts":
        row["detail"] = {"description_dates": ticket["description_dates"]}
    elif check.id == "missing_rates":
        hours = ticket["claimed_hours"]
        row["detail"] = {"rate": ticket["rate"], "claimed_hours": hours, "positive_hours": bool(hours and hours > 0)}
    elif check.id == "missing_required_fields":
        row["detail"] = {"issues": ticket["issues"]}
    return row


def alias_row(alias: dict[str, Any], numbers: dict[int, str | None], name: Callable[[int], str | None]) -> dict[str, Any]:
    """One unresolved Alias proposal: its labels, names, the Ticket pairs proposing it and the possible duplicate to open."""
    first = alias["proposed_by"][0][0]
    return {
        "labels": alias["labels"],
        "names": alias["names"],
        "decision": alias["decision"],
        "proposed_by": [
            {"excel_rows": list(pair), "ticket_numbers": [numbers.get(row) for row in pair]} for pair in alias["proposed_by"]
        ],
        "excel_row": first,
        "possible_duplicate": name(first),
    }


def missing_rate_summary(rows: list[dict[str, Any]]) -> str:
    """How many Tickets without a Rate claim positive hours, in words: their labour is unpriced, not zero."""
    positive = [row for row in rows if row["detail"]["positive_hours"]]
    hours = sum(row["detail"]["claimed_hours"] for row in positive)
    statuses: dict[str, int] = {}
    for row in positive:
        statuses[row["status"] or "an unreadable status"] = statuses.get(row["status"] or "an unreadable status", 0) + 1
    if not positive:
        return "None of them claims positive hours."
    held = ", ".join(f"{count} {status}" for status, count in sorted(statuses.items(), key=lambda item: -item[1]))
    return (
        f"{len(positive)} of them claim positive hours ({_hours(hours)} hours, unpriced; {held}); the rest claim none."
    )


def description_date_summary(rows: list[dict[str, Any]]) -> str | None:
    uncertain = sum(1 for row in rows if row["detail"]["description_dates"]["uncertain"])
    if not rows:
        return None
    return f"{uncertain} of them uncertain (no year written, a two-digit year or an unclear day/month order)."


def _hours(value: float) -> str:
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"


def _spoken(day: dt.date) -> str:
    return f"{day.day} {day.strftime('%B')} {day.year}"
