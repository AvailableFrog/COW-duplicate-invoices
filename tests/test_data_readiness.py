"""Ticket #15: the Data readiness view, six compact counts each drilling down to exactly its rows.

Expected values come from PRD section 3 ("129 blank rates; 122 of those records
have positive hours", "Work dates include 2036 and 2050"), the parse results the
API serves for each Ticket, the Alias proposals, and the raw workbook read
directly with openpyxl, never from the registry's own SQL.
"""

import datetime as dt

import openpyxl
import pytest

from conftest import HANDOFF_WORKBOOK_SHA256, WORKBOOK, running
from synthetic import ticket, without, write_workbook

CHECK_IDS = [
    "ambiguous_intervals", "anomalous_dates", "description_date_conflicts", "unresolved_identity", "missing_rates",
    "missing_required_fields",
]
READINESS_METRICS = [
    "ambiguous_interval_ticket_count", "anomalous_date_count", "description_date_conflict_count", "missing_rate_count",
    "missing_required_field_count",
]
MARIO = ["mario collymore", "mariocollymore"]


@pytest.fixture(scope="module")
def raw_tickets() -> list[dict]:
    """The committed workbook's rows as openpyxl reads them, with their Excel row."""
    book = openpyxl.load_workbook(WORKBOOK, read_only=True)
    sheet = book["Labour Tickets (1)"]
    rows = sheet.iter_rows(values_only=True)
    header = next(rows)
    tickets = [{"excel_row": index, **dict(zip(header, values))} for index, values in enumerate(rows, start=2)]
    book.close()
    return tickets


def readiness(booted, **params) -> dict:
    response = booted.get("/api/overview/data-readiness", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def counts(body: dict) -> dict[str, int | None]:
    return {check["id"]: check["count"] for check in body["checks"]}


def drill(booted, check_id: str, **params) -> dict:
    response = booted.get(f"/api/overview/data-readiness/{check_id}", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def outside(raw: dict, start: dt.date, end: dt.date) -> bool:
    return any(
        isinstance(raw[field], dt.datetime) and not start <= raw[field].date() <= end
        for field in ("Date", "Created", "Date Approved")
    )


def test_the_view_shows_six_counts_in_order_with_the_question_and_overlap_note(app):
    body = readiness(app)

    assert [check["id"] for check in body["checks"]] == CHECK_IDS
    assert body["title"] == "Data readiness"
    assert body["question"] == "Which records cannot be reliably compared or valued?"
    assert "never added together" in body["note"]
    assert [check["metric_id"] for check in body["checks"] if check["metric_id"]] == READINESS_METRICS
    assert all(isinstance(check["count"], int) for check in body["checks"])
    assert set(body["versions"]) == {"app", "registry", "rules", "parser"}


@pytest.mark.parametrize("params", [{}, {"status": "Pending"}, {"date_basis": "Date", "date_from": "2026-09-01"}])
def test_every_drilldown_holds_exactly_its_displayed_count_under_the_same_filters(app, params):
    body = readiness(app, **params)

    for check in body["checks"]:
        listed = drill(app, check["id"], **params)
        assert listed["count"] == len(listed["rows"]) == check["count"], check["id"]
        assert listed["check"]["count"] == check["count"]
        assert listed["filters"] == body["filters"]


def test_ambiguous_times_count_the_tickets_whose_parse_result_holds_an_ambiguous_interval(app):
    summary = app.get(f"/api/snapshots/{HANDOFF_WORKBOOK_SHA256}/time-parses").json()["by_status"]
    ambiguous = {row for group in summary if group["status"] == "ambiguous" for row in group["excel_rows"]}
    # A flagged parse result can still hold an Ambiguous Interval beside its flagged period.
    flagged = [row for group in summary if group["status"] == "flagged" for row in group["excel_rows"]]
    for row in flagged:
        parse = app.get(f"/api/snapshots/{HANDOFF_WORKBOOK_SHA256}/tickets/{row}/time").json()
        if any(period["confidence"] == "ambiguous" for period in parse["periods"]):
            ambiguous.add(row)

    assert counts(readiness(app))["ambiguous_intervals"] == len(ambiguous)
    listed = drill(app, "ambiguous_intervals")
    assert {row["excel_row"] for row in listed["rows"]} == ambiguous
    assert all(row["detail"]["ambiguous_periods"] for row in listed["rows"])


def test_the_default_window_covers_the_created_years_and_discloses_the_2036_and_2050_work_dates(app, raw_tickets):
    body = readiness(app)
    window = body["reporting_window"]
    created_years = {raw["Created"].year for raw in raw_tickets}

    assert (window["from"], window["to"]) == (f"{min(created_years)}-01-01", f"{max(created_years)}-12-31")
    assert window["is_default"] is True
    assert window["dates_checked"] == ["Date", "Created", "Date Approved"]
    listed = drill(app, "anomalous_dates")
    expected = [raw for raw in raw_tickets if outside(raw, dt.date(2026, 1, 1), dt.date(2026, 12, 31))]
    assert counts(body)["anomalous_dates"] == len(expected) == listed["count"]
    shown = {row["excel_row"]: row["detail"]["outside"] for row in listed["rows"]}
    work_dates = {item["value"] for items in shown.values() for item in items if item["field"] == "Date"}
    assert {"2036-09-29", "2050-12-31"} <= work_dates
    # Never reassigned: every listed date is the one recorded.
    for raw in expected:
        for item in shown[raw["excel_row"]]:
            assert item["value"] == raw[item["field"]].date().isoformat()


def test_changing_the_window_changes_the_count_and_reassigns_no_date(app, raw_tickets):
    start, end = dt.date(2026, 9, 1), dt.date(2026, 12, 31)
    narrow = readiness(app, window_from=start.isoformat())
    expected = [raw for raw in raw_tickets if outside(raw, start, end)]

    assert narrow["reporting_window"]["from"] == "2026-09-01"
    assert narrow["reporting_window"]["is_default"] is False
    assert counts(narrow)["anomalous_dates"] == len(expected) > counts(readiness(app))["anomalous_dates"]
    listed = drill(app, "anomalous_dates", window_from=start.isoformat())
    assert {row["excel_row"] for row in listed["rows"]} == {raw["excel_row"] for raw in expected}
    response = app.get(f"/api/snapshots/{HANDOFF_WORKBOOK_SHA256}/tickets/756").json()
    assert next(cell for cell in response["cells"] if cell["field"] == "Date")["value"] == "2036-09-29T00:00:00"
    wide = readiness(app, window_from="2026-01-01", window_to="2050-12-31")
    assert counts(wide)["anomalous_dates"] == 0


def test_a_window_that_ends_before_it_starts_is_refused(app):
    response = app.get("/api/overview/data-readiness", params={"window_from": "2026-10-01", "window_to": "2026-09-01"})

    assert response.status_code == 422
    assert response.json()["detail"]["field"] == "reporting_window"


def test_missing_rates_list_the_129_blank_rate_tickets_and_note_that_122_have_positive_hours(app, raw_tickets):
    blank = [raw for raw in raw_tickets if raw["Rate"] is None]
    positive = [raw for raw in blank if (raw["Regular Hours"] + raw["Overtime"] + raw["Double Time"]) > 0]
    body = readiness(app)
    listed = drill(app, "missing_rates")
    item = next(check for check in body["checks"] if check["id"] == "missing_rates")

    assert len(blank) == 129 and len(positive) == 122
    assert item["count"] == listed["count"] == 129
    assert {row["excel_row"] for row in listed["rows"]} == {raw["excel_row"] for raw in blank}
    assert sum(row["detail"]["positive_hours"] for row in listed["rows"]) == 122
    assert all(row["detail"]["rate"] == {"raw_type": "blank", "value": None} for row in listed["rows"])
    assert item["summary"].startswith("122 of them claim positive hours")
    assert "never valued at zero" in item["definition"]


def test_description_date_conflicts_list_n_with_its_spans(app):
    listed = drill(app, "description_date_conflicts")
    rows = {row["excel_row"]: row["detail"]["description_dates"] for row in listed["rows"]}

    assert {1727, 1728} <= set(rows)
    assert [reference["text"] for reference in rows[1727]["references"]] == ["9th September 2026"]
    assert rows[1728]["uncertain"] is True
    assert all(result["conflict"] for result in rows.values())


def test_the_export_has_no_missing_required_field(app):
    assert counts(readiness(app))["missing_required_fields"] == 0
    assert drill(app, "missing_required_fields")["rows"] == []


def test_missing_required_fields_count_blank_rows_and_empty_required_cells_from_the_import_issues(tmp_path):
    rows = [
        ticket(1),
        ticket(2, Employee=None),
        None,
        ticket(4, Ticket_Number=None, Rate="abc"),
        ticket(5, Regular_Hours="eight"),  # invalid, not missing
        ticket(6, Supervisor=None),  # optional
    ]
    path = write_workbook(tmp_path / "missing.xlsx", rows)
    with running(path, tmp_path / "data") as booted:
        body = readiness(booted)
        listed = drill(booted, "missing_required_fields")
        rates = drill(booted, "missing_rates")

    assert counts(body)["missing_required_fields"] == 3
    shown = {row["excel_row"]: row["detail"]["issues"] for row in listed["rows"]}
    assert set(shown) == {3, 4, 5}
    assert [issue["code"] for issue in shown[3]] == ["missing_value"]
    assert [issue["code"] for issue in shown[4]] == ["blank_row"]
    assert "missing_business_id" in [issue["code"] for issue in shown[5]]
    # A Rate that is not a number is a missing rate too, and so is a blank row's.
    assert {row["excel_row"] for row in rates["rows"]} == {4, 5}


def test_unresolved_identity_counts_proposed_aliases_and_drops_when_one_is_confirmed(tmp_path):
    with running(WORKBOOK, tmp_path) as booted:
        before = counts(readiness(booted))["unresolved_identity"]
        listed = drill(booted, "unresolved_identity")
        aliases = booted.get(f"/api/snapshots/{HANDOFF_WORKBOOK_SHA256}/aliases").json()["aliases"]
        decision = booted.client.put(
            f"/api/snapshots/{HANDOFF_WORKBOOK_SHA256}/aliases",
            json={"labels": MARIO, "decision": "confirmed", "reviewer": "Test reviewer", "rationale": "Same person"},
        )
        assert decision.status_code == 200, decision.text
        after = counts(readiness(booted))["unresolved_identity"]

    assert before == len([alias for alias in aliases if alias["decision"]["id"] == "proposed"]) == 1
    (row,) = listed["rows"]
    assert row["labels"] == MARIO
    assert row["proposed_by"] == [{"excel_rows": [829, 1072], "ticket_numbers": row["proposed_by"][0]["ticket_numbers"]}]
    assert row["possible_duplicate"].startswith("Possible duplicate ")
    assert after == before - 1


def test_unresolved_identity_drops_when_a_proposal_is_rejected_and_follows_the_filters(tmp_path):
    with running(WORKBOOK, tmp_path) as booted:
        assert counts(readiness(booted, status="Rejected"))["unresolved_identity"] == 0
        assert counts(readiness(booted, date_basis="Date", date_from="2026-09-23", date_to="2026-09-23"))[
            "unresolved_identity"
        ] == 1
        booted.client.put(
            f"/api/snapshots/{HANDOFF_WORKBOOK_SHA256}/aliases",
            json={"labels": MARIO, "decision": "rejected", "reviewer": "Test reviewer", "rationale": "Two people"},
        )
        assert counts(readiness(booted))["unresolved_identity"] == 0
        assert drill(booted, "unresolved_identity")["rows"] == []


def test_without_rate_or_description_columns_those_counts_are_disabled_with_a_reason(tmp_path):
    path = write_workbook(
        tmp_path / "no-columns.xlsx", [ticket(1)], fields=without("Rate", "Description of Job Work"),
    )
    with running(path, tmp_path / "data") as booted:
        body = readiness(booted)

    disabled = {check["id"]: check for check in body["checks"] if check["availability"]["status"] == "disabled"}
    assert set(disabled) == {"missing_rates", "description_date_conflicts"}
    assert all(check["count"] is None and check["availability"]["reason"] for check in disabled.values())


def test_the_registry_declares_the_readiness_metrics_and_an_unknown_check_is_404(app):
    registry = {metric["id"]: metric for metric in app.get("/api/metrics").json()["metrics"]}

    for metric_id in READINESS_METRICS:
        assert registry[metric_id]["grain"] == "Ticket"
    assert registry["anomalous_date_count"]["reads_reporting_window"] is True
    value = app.get("/api/metrics/anomalous_date_count", params={"window_to": "2036-12-31"}).json()
    assert value["reporting_window"]["to"] == "2036-12-31"
    assert value["value"] == 2  # the two 2050 work dates
    response = app.get("/api/overview/data-readiness/nothing")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "unknown_check"
