"""The Processing queue view: how old the unresolved submissions are, as two age-bucket bar charts.

Each chart is one registry distribution metric counted by its buckets
(metrics.AGE_BUCKETS): Pending Tickets, and Approved Tickets not yet Keyed.
Age is measured from the calendar date of Created to the analytical as-of
date, so it is age since submission, never time spent in a stage; the export
records no status history. The two populations are separate and are never
added together. A bucket's Tickets are listed by metrics.bucket_rows under the
same filters and as-of date, so the drilldown always holds the bar's count.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Queue:
    metric_id: str
    title: str
    # The population in a few words, for a Ticket opened from the chart.
    population: str


QUEUES = (
    Queue("pending_submission_age_days", "Pending submissions", "Pending"),
    Queue("approved_not_keyed_submission_age_days", "Approved, not Keyed submissions", "Approved, not Keyed"),
)

CAPTION = "Age since submission"

NOTE = (
    "Each bar counts Tickets by age since submission: the analytical as-of date minus the calendar date of Created, "
    "in whole days. It is not the time a Ticket has spent Pending or waiting to be Keyed, which the export does not "
    "record, and a current status grouped by submission date is not a history of status changes. The two charts "
    "count separate Tickets and are not added together."
)


def chart(queue: Queue, result: dict[str, Any], measured_on: str) -> dict[str, Any]:
    """One chart from its metric's evaluated result: the bucket counts, total and what was left out."""
    summary = result["summary"] or {}
    return {
        "metric_id": queue.metric_id,
        "title": queue.title,
        "population": queue.population,
        "label": result["metric"]["label"],
        "definition": result["metric"]["definition"],
        "unit": result["metric"]["unit"],
        "caption": CAPTION,
        "measured_on": measured_on,
        "chart": "bar_horizontal",
        "availability": result["availability"],
        "total": summary.get("count", 0),
        "summary": result["summary"],
        "buckets": result["buckets"] or [],
        "coverage": result["coverage"],
        "warnings": result["warnings"],
    }
