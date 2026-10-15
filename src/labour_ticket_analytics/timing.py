"""Submission and review timing: the release 1.1 Overview panel (ticket #34, PRD section 4, P1).

Every chart is built from Explore plans run under the Overview filters, so each
mark drills down through Explore's own drilldown:

- Weekly submissions by current status: one weekly `ticket_count` plan per
  Approval Status, stacked here by week, plus one plan over every status for the
  week totals. A ticket whose status is none of the three is counted in the
  totals and reported apart, never dropped.
- Submission lag and observed approval interval: one distribution plan each,
  whose exclusions (negative lags, dates outside the reporting window, negative
  intervals) are disclosed apart from the bins.
"""

from __future__ import annotations

from typing import Any

QUESTION = "Are claims entered late or awaiting disposition?"
STATUSES = ("Approved", "Pending", "Rejected")
MAX_WEEKS = 25

WEEKLY_TITLE = "Weekly submissions by current status"
WEEKLY_CAPTION = (
    "Each ticket is counted once, in the week it was submitted (Created), under its current status. It is a "
    "snapshot of current status, not a history of status changes, and it covers only the tickets in this export."
)
LAG_TITLE = "Submission lag"
LAG_NOTE = (
    "Days from the work Date to Created. Negative lags and dates outside the reporting window are listed apart, "
    "never placed in a bin."
)
INTERVAL_TITLE = "Observed approval interval"
INTERVAL_NOTE = (
    "Hours from Created to Date Approved, for Approved tickets only: a Rejected ticket is never given an approval "
    "time. It is the gap between two recorded timestamps, not the time a ticket spent in any stage."
)


def weekly_plan(status: str | None) -> dict[str, Any]:
    """Tickets by the week they were Created, for one current status or (None) for every status."""
    return {
        "metric_id": "ticket_count",
        "group_by": ["Week"],
        "filters": [{"field": "Approval Status", "operator": "eq", "value": status}] if status else [],
        "date_basis": "Created",
        "date_range": None,
        "chart": "bar_vertical",
        "sort": "label_asc",
        "limit": MAX_WEEKS,
        "include_other": False,
    }


def distribution_plan(metric_id: str) -> dict[str, Any]:
    return {
        "metric_id": metric_id,
        "group_by": [],
        "filters": [],
        "date_basis": "Created",
        "date_range": None,
        "chart": "histogram",
        "sort": "label_asc",
        "limit": 10,
        "include_other": False,
    }


def weekly(series: list[dict[str, Any]], every: dict[str, Any]) -> dict[str, Any]:
    """Stack the per-status weekly results by week; `every` is the all-status result that gives the weeks and totals.

    Each item of `series` is {"status", "request", "result"} and `every` is {"request", "result"}, where
    `result` is an executed plan payload.
    """
    counted = {
        item["status"]: {group["id"]: group["value"] for group in item["result"]["result"]["groups"]} for item in series
    }
    weeks = []
    for group in every["result"]["result"]["groups"]:
        weeks.append({
            "id": group["id"],
            "label": group["label"],
            "segments": [{"status": status, "tickets": counted[status].get(group["id"], 0)} for status in STATUSES],
            "total": group["value"],
        })
    total = every["result"]["result"]["total"] or 0
    stacked = sum(segment["tickets"] for week in weeks for segment in week["segments"])
    return {
        "title": WEEKLY_TITLE,
        "caption": WEEKLY_CAPTION,
        "statuses": list(STATUSES),
        "weeks": weeks,
        "total": total,
        # Tickets whose Approval Status is none of the three: in the week totals, in no segment.
        "other_status_tickets": total - stacked,
        "hidden_weeks": every["result"]["result"]["hidden_groups"],
        "series": series,
        "all": every,
    }
