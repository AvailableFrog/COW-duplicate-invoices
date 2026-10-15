"""Ticket #18: every Overview view and every starter plan drills down to exactly its displayed total.

Each test runs under the same four filter states, so a view and its drilldown
are always compared under the same filters, Snapshot, as-of date and versions:
all data, one status, one job, and a Created date range.
"""

from __future__ import annotations

import pytest

FILTER_STATES = {
    "all data": {},
    "status Pending": {"status": "Pending"},
    "job 41215": {"job": 41215},
    "Created 15-30 September": {"date_basis": "Created", "date_from": "2026-09-15", "date_to": "2026-09-30"},
}
STATES = pytest.mark.parametrize("params", list(FILTER_STATES.values()), ids=list(FILTER_STATES))
CONTEXT = ("snapshot_fingerprint", "as_of", "versions", "filters")


def get(app, path: str, **params) -> dict:
    response = app.get(path, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def same_context(view: dict, drilled: dict, label: str) -> None:
    for key in CONTEXT:
        assert drilled[key] == view[key], (label, key)


def metric_rows(app, metric_id: str, params: dict) -> dict:
    return get(app, f"/api/metrics/{metric_id}", rows="true", **params)


def inherited(params: dict) -> dict | None:
    """The Overview filter bar's state as a plan inherits it."""
    if not params:
        return None
    return {
        "date_basis": params.get("date_basis"),
        "date_from": params.get("date_from"),
        "date_to": params.get("date_to"),
        "statuses": [params["status"]] if "status" in params else [],
        "jobs": [params["job"]] if "job" in params else [],
    }


@STATES
def test_every_header_tile_drills_down_to_exactly_the_tickets_it_counts(app, params):
    view = get(app, "/api/overview/tiles", **params)

    for tile in view["tiles"]:
        drilled = metric_rows(app, tile["metric_id"], params)
        same_context(view, drilled, tile["metric_id"])
        assert drilled["value"] == tile["value"], tile["metric_id"]
        # A tile counting possible duplicates shows its ticket count; every other tile counts tickets.
        shown_tickets = tile["tickets"] if tile["tickets"] is not None else tile["value"]
        assert len(drilled["contributing_rows"]) == shown_tickets, tile["metric_id"]


@STATES
def test_the_flagged_duplicates_list_holds_exactly_the_tickets_the_tile_counts(app, params):
    view = get(app, "/api/flagged-duplicates", **params)
    tile = metric_rows(app, "flagged_duplicate_count", params)

    same_context(view, tile, "flagged_duplicates")
    assert sorted(entry["excel_row"] for entry in view["flagged_duplicates"]) == tile["contributing_rows"]
    assert len(view["flagged_duplicates"]) == tile["value"]


@STATES
def test_every_pattern_matrix_cell_drills_down_to_a_list_whose_ticket_total_is_the_cell(app, params):
    view = get(app, "/api/review-priorities", **params)
    checked = 0

    for row in view["pattern_matrix"]["rows"]:
        pattern = row["pattern"]["id"]
        for cell in row["cells"]:
            if cell["tickets"] == 0:
                continue
            state = cell["source_state"]
            drilled = get(app, "/api/review-priorities", pattern=pattern, source_state=state, **params)
            same_context(view, drilled, f"{pattern}/{state}")
            selected = {
                member["excel_row"]
                for item in drilled["possible_duplicates"]
                for member in item["members"]
                if member["in_selection"]
            }
            assert drilled["pattern_filter"]["totals"]["tickets"] == cell["tickets"] == len(selected), (pattern, state)
            checked += 1
    if not params.get("job"):
        assert checked > 0


@STATES
def test_every_processing_queue_bucket_drills_down_to_its_count_and_the_buckets_sum_to_the_chart(app, params):
    view = get(app, "/api/overview/processing-queue", **params)

    for chart in view["charts"]:
        listed: set[int] = set()
        for bucket in chart["buckets"]:
            drilled = get(app, f"/api/metrics/{chart['metric_id']}/buckets/{bucket['id']}", **params)
            same_context(view, drilled, f"{chart['metric_id']}/{bucket['id']}")
            assert drilled["tickets"] == len(drilled["rows"]) == bucket["tickets"], (chart["metric_id"], bucket["id"])
            listed |= {row["excel_row"] for row in drilled["rows"]}
        assert len(listed) == chart["total"], chart["metric_id"]


@STATES
def test_every_data_readiness_count_drills_down_to_exactly_its_rows(app, params):
    view = get(app, "/api/overview/data-readiness", **params)

    for check in view["checks"]:
        drilled = get(app, f"/api/overview/data-readiness/{check['id']}", **params)
        same_context(view, drilled, check["id"])
        assert drilled["count"] == len(drilled["rows"]) == check["count"], check["id"]


@STATES
def test_every_value_figure_drills_down_to_the_tickets_it_values(app, params):
    view = get(app, "/api/overview/value-context", **params)

    for figure in view["figures"]:
        drilled = metric_rows(app, figure["metric_id"], params)
        same_context(view, drilled, figure["id"])
        assert drilled["value"] == figure["value"], figure["id"]
        assert len(drilled["contributing_rows"]) == figure["tickets"], figure["id"]


@STATES
def test_every_starter_plan_drills_down_to_its_chart_total_and_every_bar_under_the_inherited_filters(app, params):
    starters = get(app, "/api/explore")["starters"]
    assert len(starters) == 6

    for starter in starters:
        body = {"plan": starter["plan"], "inherited": inherited(params)}
        executed = app.client.post("/api/plans/execute", json=body)
        assert executed.status_code == 200, executed.text
        result = executed.json()
        drilled = app.client.post("/api/plans/drilldown", json={**body, "group": None}).json()

        for key in ("snapshot_fingerprint", "as_of", "versions", "filters", "plan"):
            assert drilled[key] == result[key], (starter["id"], key)
        assert drilled["chart_total"] == result["result"]["total"], starter["id"]
        assert drilled["reproduces"] is True, starter["id"]
        for bar in result["result"].get("bars", []):
            listed = app.client.post("/api/plans/drilldown", json={**body, "group": bar["id"]}).json()
            assert listed["reproduces"] is True, (starter["id"], bar["id"])
            assert listed["chart_total"] == bar["value"], (starter["id"], bar["id"])
