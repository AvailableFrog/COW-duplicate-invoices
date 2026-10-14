"""Ticket #3: invalid cells and defective business IDs stay visible Tickets carrying issue flags."""

import datetime as dt

import pytest

from conftest import boot, shutdown
from synthetic import ticket, write_workbook


@pytest.fixture
def flagged(tmp_path):
    """Boot a synthetic workbook and return (header, fetch-ticket-by-excel-row)."""
    booted = None

    def start(tickets, **kwargs):
        nonlocal booted
        workbook = write_workbook(tmp_path / "flagged.xlsx", tickets, **kwargs)
        booted = boot(workbook, tmp_path)
        header = booted.get("/api/snapshot").json()["snapshot"]

        def fetch(excel_row):
            response = booted.get(f"/api/snapshots/{header['fingerprint']}/tickets/{excel_row}")
            assert response.status_code == 200
            return response.json()

        return header, fetch

    yield start
    if booted is not None:
        shutdown(booted)


def codes(payload) -> list[tuple[str, str]]:
    return [(issue["field"], issue["code"]) for issue in payload["issues"]]


def cell(payload, field_name):
    return next(c for c in payload["cells"] if c["field"] == field_name)


def test_a_non_numeric_hours_cell_stays_a_visible_ticket_with_an_issue_flag(flagged):
    header, fetch = flagged([ticket(1), ticket(2, Regular_Hours="eight")])

    bad = fetch(3)
    assert header["row_count"] == 2
    assert header["import_issue_count"] == 1
    assert header["import_issues"] == [
        {**header["import_issues"][0], "excel_row": 3, "field": "Regular Hours", "code": "invalid_number"}
    ]
    assert "eight" in header["import_issues"][0]["message"]
    assert cell(bad, "Regular Hours") == {**cell(bad, "Regular Hours"), "raw_type": "str", "value": "eight"}
    assert codes(bad) == [("Regular Hours", "invalid_number")]
    assert fetch(2)["issues"] == []


def test_locale_dependent_date_text_is_flagged_not_guessed_and_iso_text_is_accepted(flagged):
    header, fetch = flagged([
        ticket(1, Date="03/10/2026"),
        ticket(2, Date="2026-09-28", Created="2026-10-02T18:56:00", Modified="2026-10-05 07:48"),
        ticket(3, Date_Approved=46000),
    ])

    locale = fetch(2)
    assert codes(locale) == [("Date", "invalid_date")]
    assert cell(locale, "Date")["value"] == "03/10/2026"
    assert "not guessed" in locale["issues"][0]["message"]
    assert fetch(3)["issues"] == []
    assert codes(fetch(4)) == [("Date Approved", "invalid_date")]
    assert header["import_issue_count"] == 2


def test_unknown_status_and_boolean_values_are_flagged_not_coerced(flagged):
    header, fetch = flagged([
        ticket(1, Approval_Status="approved"),
        ticket(2, Approval_Status="On hold"),
        ticket(3, Keyed="yes"),
        ticket(4, Keyed=1),
        ticket(5, Keyed="FALSE", Approval_Status="Rejected"),
        ticket(6, Keyed=False, Approval_Status="Pending"),
    ])

    assert codes(fetch(2)) == [("Approval Status", "unknown_status")]
    assert cell(fetch(2), "Approval Status")["value"] == "approved"
    assert codes(fetch(3)) == [("Approval Status", "unknown_status")]
    assert codes(fetch(4)) == [("Keyed", "unknown_boolean")]
    assert codes(fetch(5)) == [("Keyed", "unknown_boolean")]
    assert cell(fetch(5), "Keyed") == {**cell(fetch(5), "Keyed"), "raw_type": "int", "value": 1}
    assert codes(fetch(6)) == [("Keyed", "unknown_boolean")]
    assert cell(fetch(6), "Keyed")["value"] == "FALSE"
    assert fetch(7)["issues"] == []
    assert header["import_issue_count"] == 5


def test_job_numbers_must_be_whole_numbers_without_grouping_separators(flagged):
    header, fetch = flagged([
        ticket(1, Job_Number=0),
        ticket(2, Job_Number="41215"),
        ticket(3, Job_Number="41,215"),
        ticket(4, Job_Number=412.5),
        ticket(5, Job_Number="Beachlands"),
    ])

    assert fetch(2)["issues"] == []
    assert fetch(3)["issues"] == []
    assert codes(fetch(4)) == [("Job Number", "invalid_number")]
    assert codes(fetch(5)) == [("Job Number", "invalid_number")]
    assert codes(fetch(6)) == [("Job Number", "invalid_number")]
    assert header["import_issue_count"] == 3


def test_missing_and_repeated_business_ids_stay_visible_with_flags(flagged):
    header, fetch = flagged([
        ticket(1, Ticket_Number="L000100", ID=500),
        ticket(2, Ticket_Number=None),
        ticket(3, Ticket_Number="L000100", ID="500"),
        ticket(4, ID=None),
        ticket(5, Ticket_Number="   "),
    ])

    assert header["row_count"] == 5
    assert codes(fetch(2)) == [("Ticket Number", "repeated_business_id"), ("ID", "repeated_business_id")]
    assert "4" in fetch(2)["issues"][0]["message"]
    assert codes(fetch(3)) == [("Ticket Number", "missing_business_id")]
    assert codes(fetch(4)) == [("Ticket Number", "repeated_business_id"), ("ID", "repeated_business_id")]
    assert "2" in fetch(4)["issues"][0]["message"]
    assert codes(fetch(5)) == [("ID", "missing_business_id")]
    assert codes(fetch(6)) == [("Ticket Number", "missing_business_id")]
    assert cell(fetch(6), "Ticket Number")["value"] == "   "
    assert header["import_issue_count"] == 7


def test_a_blank_required_cell_is_flagged_and_a_blank_optional_cell_is_not(flagged):
    header, fetch = flagged([
        ticket(1, Regular_Hours=None, Employee=" "),
        ticket(2, Rate=None, Date_Approved=None, Email_Address=None),
    ])

    assert codes(fetch(2)) == [("Employee", "missing_value"), ("Regular Hours", "missing_value")]
    assert cell(fetch(2), "Regular Hours")["raw_type"] == "blank"
    assert fetch(3)["issues"] == []
    assert header["import_issue_count"] == 2


def test_a_formula_cell_is_imported_as_its_formula_text_without_evaluation(flagged):
    header, fetch = flagged([
        ticket(1, Regular_Hours="=4+4", Description_of_Job_Work='=HYPERLINK("http://example.invalid","x")'),
        ticket(2, Overtime="#N/A"),
    ])

    formula = fetch(2)
    assert cell(formula, "Regular Hours") == {**cell(formula, "Regular Hours"), "raw_type": "formula", "value": "=4+4"}
    assert cell(formula, "Description of Job Work")["raw_type"] == "formula"
    assert codes(formula) == [("Regular Hours", "formula_not_evaluated"), ("Description of Job Work", "formula_not_evaluated")]
    assert cell(fetch(3), "Overtime") == {**cell(fetch(3), "Overtime"), "raw_type": "error", "value": "#N/A"}
    assert codes(fetch(3)) == [("Overtime", "error_value")]
    assert header["import_issue_count"] == 3


def test_a_raw_zero_in_time_stays_zero_and_is_not_flagged(flagged):
    header, fetch = flagged([ticket(1, Time=0), ticket(2, Time=730.43)])

    zero = fetch(2)
    assert cell(zero, "Time") == {**cell(zero, "Time"), "raw_type": "int", "value": 0}
    assert zero["issues"] == []
    assert cell(fetch(3), "Time")["value"] == 730.43
    assert header["import_issue_count"] == 0
