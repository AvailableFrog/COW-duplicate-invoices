"""Ticket #2: the Snapshot header the consultant cites in the meeting."""

from conftest import HANDOFF_WORKBOOK_SHA256


def test_header_reports_row_and_field_counts_from_the_import(app):
    response = app.get("/api/snapshot")

    assert response.status_code == 200
    body = response.json()
    assert body["snapshot"]["row_count"] == 2836
    assert body["snapshot"]["field_count"] == 22


def test_header_identifies_the_export_the_numbers_came_from(app):
    body = app.get("/api/snapshot").json()

    snapshot = body["snapshot"]
    assert snapshot["fingerprint"] == HANDOFF_WORKBOOK_SHA256
    assert snapshot["fingerprint_algorithm"] == "sha256"
    assert snapshot["sheet"] == "Labour Tickets (1)"
    assert snapshot["workbook_name"] == "Labour Tickets Export.xlsx"
    assert snapshot["import_issues"] == []
    assert snapshot["import_issue_count"] == 0


def test_header_states_the_as_of_date_as_an_assumption(app):
    body = app.get("/api/snapshot").json()

    assert body["as_of"]["date"] == "2026-10-08"
    assert body["as_of"]["is_assumption"] is True
    assert body["as_of"]["note"]


def test_header_lists_the_22_source_fields_in_workbook_order(app):
    body = app.get("/api/snapshot").json()

    assert body["snapshot"]["fields"] == [
        "Employee", "Occupation", "Ticket Number", "Job Name", "Job Number", "Date", "Time",
        "Regular Hours", "Overtime", "Double Time", "Job Work Pay", "Description of Job Work",
        "Supervisor", "Approval Status", "Modified", "Created", "ID", "Email Address", "Keyed",
        "Rate", "Date Approved", "Modified By",
    ]
