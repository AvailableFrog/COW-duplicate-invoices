"""Ticket #12: the Processing queue, two age-since-submission bar charts with a drilldown per bucket.

Expected counts come from the committed workbook read directly (Approval Status, Keyed and the calendar date
of Created against the as-of date), never from the registry's own SQL.
"""

import datetime as dt

import pytest

from conftest import WORKBOOK, running
from synthetic import ticket, write_workbook

PENDING = "pending_submission_age_days"
APPROVED_NOT_KEYED = "approved_not_keyed_submission_age_days"
BUCKET_LABELS = ["0 days", "1 day", "2 days", "3 days", "4–6 days", "7–13 days", "14–29 days", "30 days or more"]


def chart(body: dict, metric_id: str) -> dict:
    return next(item for item in body["charts"] if item["metric_id"] == metric_id)


def counts(item: dict) -> dict[str, int]:
    return {bucket["label"]: bucket["tickets"] for bucket in item["buckets"]}


def drill(booted, metric_id: str, bucket_id: str, **params) -> dict:
    response = booted.get(f"/api/metrics/{metric_id}/buckets/{bucket_id}", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_the_two_charts_cover_129_pending_and_149_approved_not_keyed_tickets_from_the_registry(app):
    body = app.get("/api/overview/processing-queue").json()

    assert [item["metric_id"] for item in body["charts"]] == [PENDING, APPROVED_NOT_KEYED]
    assert [item["title"] for item in body["charts"]] == ["Pending submissions", "Approved, not Keyed submissions"]
    for metric_id, total in ((PENDING, 129), (APPROVED_NOT_KEYED, 149)):
        item = chart(body, metric_id)
        registry = app.get(f"/api/metrics/{metric_id}").json()
        assert item["total"] == total == registry["summary"]["count"]
        assert sum(bucket["tickets"] for bucket in item["buckets"]) == total
        assert item["buckets"] == registry["buckets"]
    assert body["grain"] == "Ticket"
    assert body["filters"]["description"] == "all dates"
    assert body["as_of"]["date"] == "2026-10-08"
    assert set(body["versions"]) == {"app", "registry", "rules", "parser"}


def test_buckets_count_age_since_submission_as_of_8_october(app):
    body = app.get("/api/overview/processing-queue").json()

    assert counts(chart(body, PENDING)) == dict(zip(BUCKET_LABELS, [19, 40, 34, 18, 13, 2, 2, 1]))
    assert counts(chart(body, APPROVED_NOT_KEYED)) == dict(zip(BUCKET_LABELS, [21, 20, 22, 40, 46, 0, 0, 0]))


def test_each_chart_is_labelled_age_since_submission_with_its_date_basis_never_time_in_a_stage(app):
    body = app.get("/api/overview/processing-queue").json()

    for item in body["charts"]:
        assert item["caption"] == "Age since submission"
        assert item["measured_on"] == "Created to the analytical as-of date"
        assert item["unit"] == "days"
        assert item["chart"] == "bar_horizontal"
    assert "not the time" in body["note"]
    registry = {metric["id"]: metric for metric in app.get("/api/metrics").json()["metrics"]}
    assert [bucket["label"] for bucket in registry[PENDING]["buckets"]] == BUCKET_LABELS
    assert registry[PENDING]["buckets"] == registry[APPROVED_NOT_KEYED]["buckets"]
    assert registry["pending_count"]["buckets"] == []


def test_a_bucket_drilldown_lists_its_tickets_with_created_and_age_oldest_first(app):
    body = drill(app, PENDING, "30-or-more")

    assert body["tickets"] == 1
    (row,) = body["rows"]
    # The oldest Pending ticket in the export, created on 5 September.
    assert (row["ticket_number"], row["excel_row"], row["value"]) == ("L223224", 2837, 33)
    assert row["created"].startswith("2026-09-05")
    assert row["status"] == "Pending"
    assert body["bucket"]["label"] == "30 days or more"
    assert body["metric"]["id"] == PENDING
    assert body["snapshot_fingerprint"] == app.get("/api/snapshot").json()["snapshot_fingerprint"]

    week = drill(app, PENDING, "7-13")
    assert [(row["ticket_number"], row["excel_row"], row["value"]) for row in week["rows"]] == [
        ("L225309", 1072, 11),
        ("L225598", 783, 8),
    ]


def test_the_bucket_drilldowns_reproduce_every_bucket_and_sum_to_the_chart_total(app):
    body = app.get("/api/overview/processing-queue").json()

    for item in body["charts"]:
        seen: set[int] = set()
        for bucket in item["buckets"]:
            listed = drill(app, item["metric_id"], bucket["id"])
            assert listed["tickets"] == len(listed["rows"]) == bucket["tickets"]
            assert all(bucket["min"] <= row["value"] and (bucket["max"] is None or row["value"] <= bucket["max"]) for row in listed["rows"])
            seen |= {row["excel_row"] for row in listed["rows"]}
        assert len(seen) == item["total"]
        assert seen == set(app.get(f"/api/metrics/{item['metric_id']}", params={"rows": "true"}).json()["contributing_rows"])


def test_changing_the_as_of_date_shifts_the_ages_and_the_bucket_counts(tmp_path):
    with running(WORKBOOK, tmp_path) as booted:
        booted.client.put("/api/as-of", json={"date": "2026-10-18"})
        body = booted.get("/api/overview/processing-queue").json()
        oldest = drill(booted, PENDING, "30-or-more")

    assert body["as_of"]["date"] == "2026-10-18"
    assert counts(chart(body, PENDING)) == dict(zip(BUCKET_LABELS, [0, 0, 0, 0, 0, 111, 16, 2]))
    assert counts(chart(body, APPROVED_NOT_KEYED)) == dict(zip(BUCKET_LABELS, [0, 0, 0, 0, 0, 103, 46, 0]))
    assert [(row["ticket_number"], row["value"]) for row in oldest["rows"]] == [("L223224", 43), ("L224123", 34)]
    assert oldest["as_of"]["date"] == "2026-10-18"


def test_the_global_filters_narrow_both_charts_and_their_drilldowns(app):
    by_job = app.get("/api/overview/processing-queue", params={"job": 40972}).json()
    recent = app.get("/api/overview/processing-queue", params={"date_basis": "Created", "date_from": "2026-10-07"}).json()
    pending_only = app.get("/api/overview/processing-queue", params={"status": "Pending"}).json()

    assert (chart(by_job, PENDING)["total"], chart(by_job, APPROVED_NOT_KEYED)["total"]) == (11, 8)
    assert by_job["filters"]["jobs"] == [40972]
    assert (chart(recent, PENDING)["total"], chart(recent, APPROVED_NOT_KEYED)["total"]) == (59, 41)
    assert counts(chart(recent, PENDING)) == dict(zip(BUCKET_LABELS, [19, 40, 0, 0, 0, 0, 0, 0]))
    assert (chart(pending_only, PENDING)["total"], chart(pending_only, APPROVED_NOT_KEYED)["total"]) == (129, 0)

    for item in by_job["charts"]:
        listed = [drill(app, item["metric_id"], bucket["id"], job=40972) for bucket in item["buckets"]]
        assert sum(len(body["rows"]) for body in listed) == item["total"]
        assert all(body["filters"]["jobs"] == [40972] for body in listed)
    one_day = drill(app, PENDING, "1", date_basis="Created", date_from="2026-10-07")
    assert one_day["tickets"] == 40
    assert all(row["created"].startswith("2026-10-07") for row in one_day["rows"])


def test_an_unknown_bucket_or_a_metric_without_buckets_is_refused(app):
    unknown = app.get(f"/api/metrics/{PENDING}/buckets/1-week")
    unbucketed = app.get("/api/metrics/pending_count/buckets/0")
    missing = app.get("/api/metrics/no_such_metric/buckets/0")

    assert unknown.status_code == 404
    assert unknown.json()["detail"]["code"] == "unknown_bucket"
    assert unbucketed.status_code == 404
    assert unbucketed.json()["detail"]["code"] == "no_buckets"
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "unknown_metric"


@pytest.mark.parametrize(
    ("days", "label"),
    [(0, "0 days"), (3, "3 days"), (4, "4–6 days"), (6, "4–6 days"), (7, "7–13 days"), (13, "7–13 days"),
     (14, "14–29 days"), (29, "14–29 days"), (30, "30 days or more"), (400, "30 days or more")],
)
def test_bucket_edges_are_whole_days_inclusive(days, label, tmp_path):
    as_of = dt.date(2026, 10, 8)
    created = dt.datetime.combine(as_of - dt.timedelta(days=days), dt.time(23, 59))
    workbook = write_workbook(tmp_path / "edge.xlsx", [ticket(1, Approval_Status="Pending", Created=created)])
    with running(workbook, tmp_path) as booted:
        body = booted.get("/api/overview/processing-queue").json()

    assert {key: value for key, value in counts(chart(body, PENDING)).items() if value} == {label: 1}


def test_tickets_left_out_of_the_ages_are_reported_beside_the_chart_and_never_bucketed(tmp_path):
    workbook = write_workbook(
        tmp_path / "exclusions.xlsx",
        [
            ticket(1, Approval_Status="Pending", Created=dt.datetime(2026, 10, 6, 9, 0)),
            ticket(2, Approval_Status="Pending", Created=dt.datetime(2026, 10, 20, 9, 0)),
            ticket(3, Approval_Status="Pending", Created="sometime"),
        ],
    )
    with running(workbook, tmp_path) as booted:
        body = booted.get("/api/overview/processing-queue").json()
        listed = [drill(booted, PENDING, bucket["id"]) for bucket in chart(body, PENDING)["buckets"]]

    pending = chart(body, PENDING)
    assert pending["total"] == 1
    assert counts(pending)["2 days"] == 1
    excluded = {item["code"]: item["excel_rows"] for item in pending["coverage"]["excluded"]}
    assert excluded == {"created_after_as_of": [3], "created_unusable": [4]}
    assert len(pending["warnings"]) == 2
    assert [row["excel_row"] for body in listed for row in body["rows"]] == [2]
