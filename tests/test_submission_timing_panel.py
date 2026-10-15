"""Ticket #34: submission and review timing on the Overview.

Three charts, each built from Explore plans under the Overview filters so every
mark drills down through Explore's own drilldown: weekly submissions stacked by
current status (one weekly plan per status, plus one for all statuses), the
submission-lag distribution and the observed approval-interval distribution.
"""

from conftest import running
from synthetic import ticket, write_workbook

STATUSES = ["Approved", "Pending", "Rejected"]


def panel(app, **params) -> dict:
    response = app.get("/api/overview/submission-timing", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def drill(app, request: dict, group: str | None) -> dict:
    response = app.client.post("/api/plans/drilldown", json={**request, "group": group})
    assert response.status_code == 200, response.text
    return response.json()


def test_weekly_submissions_stack_every_ticket_by_its_current_status(app):
    weekly = panel(app)["weekly"]

    assert [series["status"] for series in weekly["series"]] == STATUSES
    assert [week["id"] for week in weekly["weeks"]] == [
        "2026-08-31", "2026-09-07", "2026-09-14", "2026-09-21", "2026-09-28", "2026-10-05",
    ]
    week = next(item for item in weekly["weeks"] if item["id"] == "2026-09-07")
    assert week["label"] == "Week of 7 Sep 2026"
    assert week["segments"] == [
        {"status": "Approved", "tickets": 493}, {"status": "Pending", "tickets": 0}, {"status": "Rejected", "tickets": 27},
    ]
    assert week["total"] == 520
    assert weekly["total"] == sum(item["total"] for item in weekly["weeks"]) == 2836
    assert weekly["other_status_tickets"] == 0
    assert weekly["all"]["result"]["result"]["total"] == 2836


def test_the_weekly_caption_says_current_status_not_a_history(app):
    weekly = panel(app)["weekly"]

    assert "current status" in weekly["caption"]
    assert "not a history of status changes" in weekly["caption"]
    assert weekly["title"] == "Weekly submissions by current status"


def test_every_week_and_status_segment_drills_down_to_exactly_its_tickets(app):
    weekly = panel(app)["weekly"]
    requests = {series["status"]: series["request"] for series in weekly["series"]}

    for week in weekly["weeks"]:
        for segment in week["segments"]:
            if segment["tickets"] == 0:
                continue
            listed = drill(app, requests[segment["status"]], week["id"])
            assert listed["reproduces"] is True, (week["id"], segment["status"])
            assert listed["chart_total"] == len(listed["rows"]) == segment["tickets"], (week["id"], segment["status"])
            assert {row["status"] for row in listed["rows"]} == {segment["status"]}
        total = drill(app, weekly["all"]["request"], week["id"])
        assert total["chart_total"] == week["total"], week["id"]


def test_the_lag_distribution_discloses_negative_lags_and_out_of_window_dates_apart_from_its_bins(app):
    lag = panel(app)["lag"]
    exclusions = {item["code"]: item for item in lag["result"]["how_calculated"]["exclusions"]}

    assert lag["result"]["result"]["form"] == "distribution"
    assert lag["result"]["result"]["contributing_tickets"] == 2817
    assert exclusions["negative_lag"]["tickets"] == 16
    assert exclusions["date_outside_reporting_window"]["excel_rows"] == [756, 1265, 2502]
    assert lag["title"] == "Submission lag"


def test_the_approval_interval_counts_approved_tickets_only_and_says_what_it_leaves_out(app):
    interval = panel(app)["interval"]
    exclusions = {item["code"]: item for item in interval["result"]["how_calculated"]["exclusions"]}

    assert interval["result"]["result"]["contributing_tickets"] == 2610  # 2,611 Approved less one negative interval
    assert exclusions["negative_interval"]["excel_rows"] == [773]
    assert "Approved tickets only" in interval["note"]
    assert "not the time a ticket spent in any stage" in interval["note"]


def test_every_bin_of_both_distributions_drills_down_to_exactly_its_tickets(app):
    body = panel(app)
    for key in ("lag", "interval"):
        chart = body[key]
        whole = drill(app, chart["request"], None)
        assert whole["reproduces"] is True, key
        for group in chart["result"]["result"]["groups"]:
            if group["value"] == 0:
                continue
            listed = drill(app, chart["request"], group["id"])
            assert listed["reproduces"] is True, (key, group["id"])
            assert listed["chart_total"] == group["value"], (key, group["id"])


def test_the_panel_follows_the_overview_filters(app):
    pending = panel(app, status="Pending")["weekly"]
    one_job = panel(app, job=41215)

    assert pending["total"] == 129
    assert all(segment["tickets"] == 0 for week in pending["weeks"] for segment in week["segments"] if segment["status"] != "Pending")
    assert one_job["weekly"]["all"]["result"]["filters"]["jobs"] == [41215]
    assert one_job["lag"]["result"]["filters"]["jobs"] == [41215]


def test_a_ticket_with_an_unreadable_status_is_reported_rather_than_left_out_silently(tmp_path):
    workbook = write_workbook(
        tmp_path / "export.xlsx",
        [ticket(1), ticket(2, Approval_Status="Pending"), ticket(3, Approval_Status="Aproved")],
    )
    with running(workbook, tmp_path / "data") as booted:
        weekly = panel(booted)["weekly"]

    assert weekly["total"] == 3
    assert weekly["other_status_tickets"] == 1
    assert sum(segment["tickets"] for week in weekly["weeks"] for segment in week["segments"]) == 2
