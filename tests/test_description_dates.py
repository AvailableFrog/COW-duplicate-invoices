"""Ticket #15: the Description-date exception, a Ticket-level exception that never links Tickets.

Expected values come from the evidence report's example N (rows 1727/1728,
docs/source/labour-ticket-report-readable.md: "Both Date cells say 11 September
... but descriptions name the 9th and the 7th"), PRD section 5 and the raw
workbook. Forms the export lacks are built with tests/synthetic.py.
"""

import datetime as dt

import pytest

from conftest import HANDOFF_WORKBOOK_SHA256, running
from synthetic import ticket, without, write_workbook

DESCRIPTION = "Description of Job Work"


def ticket_evidence(booted, excel_row: int, fingerprint: str = HANDOFF_WORKBOOK_SHA256) -> dict:
    response = booted.get(f"/api/snapshots/{fingerprint}/tickets/{excel_row}/evidence")
    assert response.status_code == 200, response.text
    return response.json()


def dates_of(booted, excel_row: int, fingerprint: str = HANDOFF_WORKBOOK_SHA256) -> dict:
    (member,) = ticket_evidence(booted, excel_row, fingerprint)["members"]
    return member["description_dates"]


def cell(booted, excel_row: int, field: str, fingerprint: str = HANDOFF_WORKBOOK_SHA256) -> dict:
    cells = booted.get(f"/api/snapshots/{fingerprint}/tickets/{excel_row}").json()["cells"]
    return next(item for item in cells if item["field"] == field)


def fingerprint_of(booted) -> str:
    return booted.get("/api/snapshot").json()["snapshot_fingerprint"]


def test_n_row_1727_carries_its_description_date_span_and_keeps_its_recorded_date(app):
    result = dates_of(app, 1727)
    description = cell(app, 1727, DESCRIPTION)["value"]

    assert description == "Ticket for the 9th September 2026"
    assert result["status"] == "conflict"
    assert result["date"] == "2026-09-11"
    (reference,) = result["references"]
    assert reference["text"] == "9th September 2026"
    assert description[reference["start"]:reference["end"]] == reference["text"]
    assert reference["interpretation"] == "9 September 2026"
    assert reference["readings"] == [{"from": "2026-09-09", "to": "2026-09-09"}]
    assert reference["differs_from_date"] is True
    assert reference["uncertain"] is False and reference["year_written"] is True
    # Description text never overwrites Date.
    assert cell(app, 1727, "Date")["value"] == "2026-09-11T00:00:00"


def test_n_row_1728_names_the_7th_without_a_year_so_its_reading_is_flagged_uncertain(app):
    result = dates_of(app, 1728)

    assert result["status"] == "conflict"
    assert result["uncertain"] is True
    (reference,) = result["references"]
    assert reference["text"] == "7th of September"
    assert reference["year_written"] is False
    assert reference["uncertain"] is True
    assert reference["uncertainty"] == ["year_omitted"]
    assert "no year" in reference["interpretation"]
    assert reference["readings"] == [{"from": "2026-09-07", "to": "2026-09-07"}]
    assert any("year of Date" in note for note in reference["notes"])
    assert cell(app, 1728, "Date")["value"] == "2026-09-11T00:00:00"


def test_the_exception_creates_no_candidate_for_n(app):
    for row in (1727, 1728):
        response = app.get(f"/api/snapshots/{HANDOFF_WORKBOOK_SHA256}/tickets/{row}/possible-duplicate")
        assert response.status_code == 404
        assert ticket_evidence(app, row)["possible_duplicate"] is None
    explanation = app.get(f"/api/snapshots/{HANDOFF_WORKBOOK_SHA256}/pairs/1727/1728").json()
    assert explanation["linked"] is False
    assert not any(rule["matched"] for rule in explanation["rules"])
    assert "description_date_exception" not in {rule["rule_id"] for rule in explanation["rules"]}
    # Both tickets carry the exception in the pair view, with their own Dates untouched.
    assert [member["description_dates"]["status"] for member in explanation["members"]] == ["conflict", "conflict"]


def test_the_exception_is_versioned_with_the_rules(app):
    result = dates_of(app, 1727)
    versions = app.get("/api/snapshot").json()["versions"]

    assert result["rule_version"] == versions["rules"]
    assert result["check"] == "description_date_exception"
    assert result["pattern"] == {"id": "service_date_in_description", "number": 6, "label": "Service date in description"}


RECOGNISED = [
    # description, Date, expected texts, interpretations, readings, uncertainty per reference, status
    ("Ticket for Sept 12", dt.datetime(2026, 9, 14), ["Sept 12"], ["12 September (no year written)"],
     [[("2026-09-12", "2026-09-12")]], [["year_omitted"]], "conflict"),
    ("Done 12th September 2026", dt.datetime(2026, 9, 12), ["12th September 2026"], ["12 September 2026"],
     [[("2026-09-12", "2026-09-12")]], [[]], "agrees"),
    ("Back on 2026-10-30", dt.datetime(2026, 10, 9), ["2026-10-30"], ["30 October 2026"],
     [[("2026-10-30", "2026-10-30")]], [[]], "conflict"),
    # Both numbers could be the month: both readings kept, neither chosen.
    ("Sheet 12/09", dt.datetime(2026, 9, 14), ["12/09"], ["12 September or 9 December (no year written)"],
     [[("2026-09-12", "2026-09-12"), ("2026-12-09", "2026-12-09")]], [["year_omitted", "day_month_order"]], "conflict"),
    # Only one order is a date, so it is read that way and nothing is uncertain.
    ("Sheet 13/09/2026", dt.datetime(2026, 9, 14), ["13/09/2026"], ["13 September 2026"],
     [[("2026-09-13", "2026-09-13")]], [[]], "conflict"),
    # A range with one end giving only the day borrows the other end's month; Date inside it agrees.
    ("Trucking from 2nd to 8th Sep", dt.datetime(2026, 9, 5), ["2nd to 8th Sep"], ["2 to 8 September (no year written)"],
     [[("2026-09-02", "2026-09-08")]], [["year_omitted"]], "agrees"),
    ("Incentive 4 Sep 26 to 10 Sep 26.", dt.datetime(2026, 9, 11), ["4 Sep 26 to 10 Sep 26"],
     ["4 September 2026 to 10 September 2026"], [[("2026-09-04", "2026-09-10")]], [["two_digit_year"]], "conflict"),
]


@pytest.fixture(scope="module")
def forms(tmp_path_factory):
    rows = [
        ticket(index + 1, Description_of_Job_Work=text, Date=date)
        for index, (text, date, *_rest) in enumerate(RECOGNISED)
    ]
    rows += [
        ticket(50, Description_of_Job_Work="7/30am - 4/30pm, 1/2 day, heat 6.5hrs, $13.86, the 10th, 31 Sep"),
        ticket(51, Description_of_Job_Work=None),
        ticket(52, Description_of_Job_Work=2026),
        ticket(53, Description_of_Job_Work="Ticket for the 9th September", Date=None),
    ]
    path = write_workbook(tmp_path_factory.mktemp("forms") / "forms.xlsx", rows)
    with running(path, tmp_path_factory.mktemp("forms-data")) as booted:
        yield booted


@pytest.mark.parametrize("index", range(len(RECOGNISED)))
def test_each_recognised_form_is_read_with_its_span_interpretation_and_uncertainty(forms, index):
    text, _, spans, interpretations, readings, uncertainty, status = RECOGNISED[index]
    result = dates_of(forms, index + 2, fingerprint_of(forms))

    assert result["status"] == status
    assert [reference["text"] for reference in result["references"]] == spans
    for reference in result["references"]:
        assert text[reference["start"]:reference["end"]] == reference["text"]
    assert [reference["interpretation"] for reference in result["references"]] == interpretations
    assert [
        [(reading["from"], reading["to"]) for reading in reference["readings"]] for reference in result["references"]
    ] == readings
    assert [reference["uncertainty"] for reference in result["references"]] == uncertainty
    assert result["conflict"] is (status == "conflict")


def test_times_fractions_amounts_and_a_day_without_a_month_are_not_dates(forms):
    fingerprint = fingerprint_of(forms)
    offset = len(RECOGNISED) + 2

    assert dates_of(forms, offset, fingerprint)["status"] == "no_date_reference"
    assert dates_of(forms, offset + 1, fingerprint)["status"] == "blank"
    assert dates_of(forms, offset + 2, fingerprint)["status"] == "not_text"
    unusable = dates_of(forms, offset + 3, fingerprint)
    assert unusable["status"] == "date_unusable"
    assert unusable["conflict"] is False
    assert [reference["differs_from_date"] for reference in unusable["references"]] == [None]


def test_a_possible_duplicate_member_shows_its_description_dates_in_the_drawer(tmp_path):
    claim = dict(Employee="Toyna Elcock", Date=dt.datetime(2026, 9, 11), Time=0, Regular_Hours=0, Job_Work_Pay=20)
    rows = [
        ticket(1, **claim, Description_of_Job_Work="Ticket for the 9th September 2026"),
        ticket(2, **claim, Description_of_Job_Work="Ticket for the 7th of September"),
    ]
    path = write_workbook(tmp_path / "pair.xlsx", rows)
    with running(path, tmp_path / "data") as booted:
        fingerprint = fingerprint_of(booted)
        response = booted.get(f"/api/snapshots/{fingerprint}/tickets/2/possible-duplicate")
        assert response.status_code == 200, response.text
        body = response.json()

    # Linked by the Strict repeat on the claim fields, never by the dates in their descriptions.
    assert {candidate["rule_id"] for candidate in body["candidates"]} == {"strict_repeat", "repeated_component"}
    shown = {member["excel_row"]: member["description_dates"] for member in body["members"]}
    assert [reference["text"] for reference in shown[2]["references"]] == ["9th September 2026"]
    assert [reference["text"] for reference in shown[3]["references"]] == ["7th of September"]
    assert shown[3]["uncertain"] is True


def test_without_a_description_column_the_check_is_disabled(tmp_path):
    path = write_workbook(tmp_path / "no-description.xlsx", [ticket(1)], fields=without(DESCRIPTION))
    with running(path, tmp_path / "data") as booted:
        fingerprint = fingerprint_of(booted)
        result = dates_of(booted, 2, fingerprint)
        header = booted.get("/api/snapshot").json()["snapshot"]

    assert result["status"] == "disabled"
    assert result["references"] == []
    assert "no Description of Job Work column" in result["note"]
    assert "description_date_exception" in {feature["feature"] for feature in header["disabled_features"]}
