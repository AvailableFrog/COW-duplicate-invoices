"""Ticket #4: registry metrics evaluated through the API, with their coverage disclosed."""

from conftest import running
from synthetic import ticket, without, write_workbook


def test_a_percentage_metric_returns_its_numerator_and_denominator(app):
    body = app.get("/api/metrics/pending_count").json()

    assert body["percentage"]["numerator"] == 129
    assert body["percentage"]["denominator"] == 2836
    assert body["percentage"]["denominator_metric"] == "ticket_count"
    assert round(body["percentage"]["ratio"], 4) == 0.0455


def test_a_percentage_follows_the_filters_on_both_sides(app):
    body = app.get("/api/metrics/approved_not_keyed_count", params={"status": "Approved"}).json()

    assert (body["percentage"]["numerator"], body["percentage"]["denominator"]) == (149, 2611)


def test_claimed_hours_over_the_export_have_full_coverage(app):
    body = app.get("/api/metrics/claimed_hours").json()

    assert body["value"] == 19292
    assert body["coverage"]["contributing_tickets"] == 2836
    assert body["coverage"]["excluded"] == []
    assert body["warnings"] == []


def test_claimed_hours_over_a_ticket_with_an_invalid_component_warn_instead_of_counting_zero(tmp_path):
    workbook = write_workbook(
        tmp_path / "hours.xlsx",
        [ticket(1, Regular_Hours=8), ticket(2, Regular_Hours=6, Overtime="two"), ticket(3, Regular_Hours=7, Double_Time=None)],
    )
    with running(workbook, tmp_path) as booted:
        body = booted.get("/api/metrics/claimed_hours").json()

    assert body["value"] == 8
    assert body["coverage"]["contributing_tickets"] == 1
    assert body["coverage"]["excluded"] == [
        {
            "code": "hour_component_unusable",
            "message": "Regular Hours, Overtime or Double Time is missing or not a number",
            "tickets": 2,
            "excel_rows": [3, 4],
        }
    ]
    assert len(body["warnings"]) == 1
    assert "3, 4" in body["warnings"][0]
    assert "not counted as zero" in body["warnings"][0]


def test_employee_labels_are_counted_after_normalization(app):
    assert app.get("/api/metrics/employee_label_count").json()["value"] == 142


def test_known_base_value_reconciles_and_discloses_unpriced_labour(app):
    body = app.get("/api/metrics/known_base_value_bbd").json()
    markers = app.get("/api/metrics/known_base_value_bbd", params={"job": 0, "status": "Approved"}).json()

    assert body["value"] == 341477.32
    assert markers["value"] == 3399.71
    unpriced = {item["code"]: item for item in body["coverage"]["partial"]}["unpriced_labour"]
    assert (unpriced["tickets"], unpriced["quantity"], unpriced["quantity_unit"]) == (122, 881, "hours")


def test_a_metric_needing_a_missing_column_is_disabled_with_a_reason(tmp_path):
    workbook = write_workbook(tmp_path / "no-rate.xlsx", [ticket(1)], fields=without("Rate"))
    with running(workbook, tmp_path) as booted:
        body = booted.get("/api/metrics/known_base_value_bbd").json()
        listed = {metric["id"]: metric for metric in booted.get("/api/metrics").json()["metrics"]}

    assert body["value"] is None
    assert body["availability"]["status"] == "disabled"
    assert "Rate" in body["availability"]["reason"]
    assert listed["known_base_value_bbd"]["availability"]["status"] == "disabled"


def test_a_metric_awaiting_its_rule_returns_no_number(app):
    body = app.get("/api/metrics/strict_unmarked_case_count").json()

    assert body["value"] is None
    assert body["availability"]["status"] == "awaiting_rule"


def test_negative_submission_lag_is_a_separate_exception_not_discarded_silently(app):
    body = app.get("/api/metrics/submission_lag_days").json()

    negative = {item["code"]: item for item in body["coverage"]["excluded"]}["negative_lag"]
    assert negative["tickets"] > 0
    assert body["coverage"]["contributing_tickets"] + negative["tickets"] == 2836
    assert any("Date as recorded falls after Created" in warning for warning in body["warnings"])


def test_an_unknown_metric_or_dimension_is_a_recoverable_error(app):
    unknown = app.get("/api/metrics/paid_twice_count")
    bad_group = app.get("/api/metrics/ticket_count", params={"group_by": "Email Address"})

    assert unknown.status_code == 404
    assert unknown.json()["detail"]["code"] == "unknown_metric"
    assert bad_group.status_code == 422
    assert bad_group.json()["detail"]["field"] == "group_by"


def test_source_rows_behind_a_metric_can_be_listed(app):
    body = app.get("/api/metrics/marked_ticket_count", params={"rows": "true"}).json()

    assert len(body["contributing_rows"]) == 28
    first = app.get(f"/api/snapshots/{body['snapshot_fingerprint']}/tickets/{body['contributing_rows'][0]}").json()
    cells = {cell["field"]: cell["value"] for cell in first["cells"]}
    assert (cells["Approval Status"], cells["Job Number"]) == ("Approved", 0)


def test_unpriced_labour_counts_every_usable_hour_and_zero_hours_need_no_rate(tmp_path):
    workbook = write_workbook(
        tmp_path / "rates.xlsx",
        [
            ticket(1, Rate=None, Regular_Hours=8, Overtime="two", Job_Work_Pay=10),
            ticket(2, Rate=None, Regular_Hours=0, Overtime=0, Double_Time=0, Job_Work_Pay=None),
            ticket(3, Rate=10, Regular_Hours=1, Overtime=0, Double_Time=0, Job_Work_Pay=0.005),
        ],
    )
    with running(workbook, tmp_path) as booted:
        body = booted.get("/api/metrics/known_base_value_bbd").json()

    assert body["value"] == 20.01
    assert body["coverage"]["excluded"] == []
    assert [(item["code"], item["excel_rows"], item["quantity"]) for item in body["coverage"]["partial"]] == [
        ("unpriced_labour", [2], 8),
    ]
