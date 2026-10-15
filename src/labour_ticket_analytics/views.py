"""Saved views (ticket #39): the Overview filters, or an Explore plan with its starting filters, under a name.

A view records what it was saved under: the Snapshot, the analytical as-of
date, the app, registry, rule and parser versions, and the Aliases confirmed
at the time. Reopening it compares those with what is in effect now and names
every difference; the caller reruns only when the reviewer asks, so a view
never silently shows different numbers.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from labour_ticket_analytics import plans
from labour_ticket_analytics.filters import DEFAULT_DATE_BASIS, FilterError, Filters

KINDS = ("overview", "explore")
MAX_NAME = 120


class ViewError(ValueError):
    def __init__(self, code: str, field_name: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.field = field_name
        self.status = status

    def payload(self) -> dict[str, str]:
        return {"code": self.code, "field": self.field, "message": str(self)}


def clean_name(value: Any) -> str:
    """A view's name: plain text, trimmed, 1 to 120 characters. It is shown as text, never as markup."""
    if not isinstance(value, str) or not value.strip():
        raise ViewError("missing_value", "name", "give the view a name")
    name = value.strip()
    if len(name) > MAX_NAME:
        raise ViewError("too_long", "name", f"a view name is at most {MAX_NAME} characters")
    return name


def validate(kind: Any, state: Any, fields: tuple[str, ...] | list[str]) -> dict[str, Any]:
    """Check a view's state the same way the Overview and Explore check it; returns the state unchanged."""
    if kind not in KINDS:
        raise ViewError("unknown_kind", "kind", f"a view is one of {', '.join(KINDS)}")
    if not isinstance(state, dict):
        raise ViewError("invalid_state", "state", "the view's state must be an object")
    if kind == "overview":
        filters = state.get("filters")
        if not isinstance(filters, dict):
            raise ViewError("invalid_state", "state.filters", "an Overview view holds the filter bar's state")
        try:
            Filters.build(
                fields=fields,
                date_basis=filters.get("date_basis") or DEFAULT_DATE_BASIS,
                date_from=_date(filters.get("date_from"), "date_from"),
                date_to=_date(filters.get("date_to"), "date_to"),
                jobs=_jobs(filters.get("jobs")),
                statuses=list(filters.get("statuses") or []),
            )
        except FilterError as error:
            raise ViewError("invalid_filter", f"state.filters.{error.field}", str(error)) from error
        return {"filters": filters}
    try:
        plans.validate(state.get("plan"), fields)
        plans.inherited(state.get("inherited"), fields)
    except plans.PlanError as error:
        detail = error.payload()
        raise ViewError("invalid_plan", "state.plan", detail.get("message", "the plan is not valid")) from error
    return {"plan": state.get("plan"), "inherited": state.get("inherited")}


def _date(value: Any, name: str) -> dt.date | None:
    if value in (None, ""):
        return None
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError as error:
        raise ViewError("invalid_filter", f"state.filters.{name}", f"{name} must be a date as YYYY-MM-DD") from error


def _jobs(value: Any) -> list[int]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(job, int) and not isinstance(job, bool) for job in value):
        raise ViewError("invalid_filter", "state.filters.jobs", "jobs must be a list of whole numbers")
    return value


def differences(saved_under: dict[str, Any], now: dict[str, Any]) -> list[dict[str, Any]]:
    """What changed since the view was saved, each with the saved and current values and a sentence."""
    found: list[dict[str, Any]] = []
    if saved_under["snapshot_fingerprint"] != now["snapshot_fingerprint"]:
        found.append({
            "field": "snapshot",
            "saved": saved_under["snapshot_fingerprint"],
            "now": now["snapshot_fingerprint"],
            "message": (
                f"Saved on a different export (Snapshot {saved_under['snapshot_fingerprint'][:12]}); the active one "
                f"is {now['snapshot_fingerprint'][:12]}. Run it again to see its numbers on this export."
            ),
        })
    if saved_under["as_of"] != now["as_of"]:
        found.append({
            "field": "as_of",
            "saved": saved_under["as_of"],
            "now": now["as_of"],
            "message": (
                f"Saved with the as-of date {saved_under['as_of']}; it is now {now['as_of']}, which moves ages and "
                "relative date ranges. Run it again to see the numbers as of now."
            ),
        })
    for key in sorted(set(saved_under["versions"]) | set(now["versions"])):
        if saved_under["versions"].get(key) != now["versions"].get(key):
            found.append({
                "field": f"versions.{key}",
                "saved": saved_under["versions"].get(key),
                "now": now["versions"].get(key),
                "message": (
                    f"Saved under {key} {saved_under['versions'].get(key)}; it is now {now['versions'].get(key)}, "
                    "so a definition may have changed. Run it again to see the numbers under it."
                ),
            })
    if saved_under["aliases"] != now["aliases"]:
        found.append({
            "field": "aliases",
            "saved": saved_under["aliases"],
            "now": now["aliases"],
            "message": "The confirmed Aliases have changed since it was saved. Run it again to see the numbers under them.",
        })
    return found


def with_differences(view: dict[str, Any], now: dict[str, Any]) -> dict[str, Any]:
    found = differences(view["saved_under"], now)
    return {**view, "current": not found, "differences": found}
