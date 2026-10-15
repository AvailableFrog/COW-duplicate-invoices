"""Claimed hours by job: the release 1.1 Overview panel (ticket #33, PRD section 4, P1).

The panel is a fixed Explore plan run under the Overview filters, so its
numbers, drilldowns, table and "How this was calculated" come from the same
validated, deterministic path as any Explore chart. Its default scope is the
PRD's: Approved tickets with a nonzero Job Number, stated in the title. Hours
are shown as recorded, possible repeats included; once a reviewer has linked
replaced and kept tickets, an analyst-reviewed alternative is offered beside
the recorded figure, never instead of it.

Employee-label count is not offered as a measure: it is a distinct count, so
its bars would not add up to Other or to the total, and Explore does not
chart it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SCOPE = "Approved, Job Number not 0"
QUESTION = "Where are the reported hours concentrated?"
NOTE = (
    "Hours are shown as recorded, including possible repeats: they show where hours were claimed, not how "
    "well anyone worked or what anything cost. Ten jobs have their own bar and the rest are combined as Other."
)
REVIEWED_LABEL = "Analyst-reviewed alternative: replaced tickets left out"
REVIEWED_NOTE = (
    "Leaves out only the tickets a reviewer linked as replaced by a kept ticket. It sits beside the recorded "
    "figure and changes nothing in the company's system."
)


@dataclass(frozen=True)
class Measure:
    id: str
    label: str
    title: str
    metric_id: str
    reviewed_metric_id: str | None

    def payload(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label}


MEASURES: tuple[Measure, ...] = (
    Measure("claimed_hours", "Claimed hours", f"Claimed hours by job ({SCOPE})", "claimed_hours", "reviewed_claimed_hours"),
    Measure("ticket_count", "Tickets", f"Tickets by job ({SCOPE})", "ticket_count", None),
)
MEASURE_BY_ID = {measure.id: measure for measure in MEASURES}
DEFAULT_MEASURE = MEASURES[0].id


def plan(metric_id: str) -> dict[str, Any]:
    """The panel's fixed plan for one metric: the ten jobs with the largest value, horizontal, plus Other."""
    return {
        "metric_id": metric_id,
        "group_by": ["Job Number"],
        "filters": [
            {"field": "Approval Status", "operator": "eq", "value": "Approved"},
            {"field": "Job Number", "operator": "ne", "value": 0},
        ],
        "date_basis": "Created",
        "date_range": None,
        "chart": "bar_horizontal",
        "sort": "metric_desc",
        "limit": 10,
        "include_other": True,
    }

