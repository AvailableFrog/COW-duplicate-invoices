"""Ticket #5: every Ticket's raw Time cell is parsed into a parse result under the interval confidence policy.

Expected readings come from the evidence report (docs/source/labour-ticket-report-readable.md)
and the policy in docs/prd.md ("Interval confidence policy").
"""

from conftest import HANDOFF_WORKBOOK_SHA256

LAST_EXCEL_ROW = 2837


def time_parse(app, excel_row: int, fingerprint: str = HANDOFF_WORKBOOK_SHA256) -> dict:
    response = app.get(f"/api/snapshots/{fingerprint}/tickets/{excel_row}/time")
    assert response.status_code == 200, response.text
    return response.json()


def compare(app, first: int, second: int, fingerprint: str = HANDOFF_WORKBOOK_SHA256) -> dict:
    response = app.get(f"/api/snapshots/{fingerprint}/time-comparison", params={"excel_row": [first, second]})
    assert response.status_code == 200, response.text
    return response.json()


def test_explicit_am_pm_periods_are_confident_intervals_with_the_raw_text_kept(app):
    # A, Romarian Alleyne on 2 October: rows 591 and 593.
    afternoon = time_parse(app, 591)

    assert afternoon["raw_time"] == {"raw_type": "str", "value": "12:30 PM - 4:30 PM"}
    assert afternoon["parser_version"] == afternoon["versions"]["parser"] != "0.0.0"
    assert afternoon["status"] == "confident"
    assert [
        (period["text"], period["confidence"], period["interval"]) for period in afternoon["periods"]
    ] == [("12:30 PM - 4:30 PM", "confident", {"start": "12:30", "end": "16:30"})]
    assert afternoon["periods"][0]["plausible_reading"] is None
    assert afternoon["periods"][0]["flags"] == []

    morning = time_parse(app, 593)
    assert morning["status"] == "confident"
    assert [period["interval"] for period in morning["periods"]] == [{"start": "07:30", "end": "11:30"}]


def test_confident_intervals_that_do_not_intersect_are_separate(app):
    # A: 12:30-16:30 and 07:30-11:30 on the same Date.
    comparison = compare(app, 591, 593)

    assert comparison["result"] == "separate"
    assert comparison["basis"] == "confident_intervals"
    assert comparison["assumed"] is False
    assert comparison["intersection"] == []
    assert comparison["overlap_minutes"] == 0
    assert [ticket["excel_row"] for ticket in comparison["tickets"]] == [591, 593]
    assert comparison["versions"]["parser"] == time_parse(app, 591)["parser_version"]


def test_underscore_separated_periods_are_compared_as_a_union_without_a_false_overlap_across_the_gap(app):
    # L, Weston Holder on 11 September: row 2151 claims 10:30am-2:30pm, and row
    # 2152 claims 7:30-10:30am and 2:30-4:30pm. First start to last end would
    # span the whole of 2151; the union does not.
    split = time_parse(app, 2152)

    assert split["raw_time"]["value"] == "730am 1030am _ 230pm 430pm"
    assert split["status"] == "confident"
    assert [(period["text"], period["interval"]) for period in split["periods"]] == [
        ("730am 1030am", {"start": "07:30", "end": "10:30"}),
        ("230pm 430pm", {"start": "14:30", "end": "16:30"}),
    ]
    assert [period["interval"] for period in time_parse(app, 2151)["periods"]] == [{"start": "10:30", "end": "14:30"}]

    comparison = compare(app, 2151, 2152)
    assert comparison["result"] == "separate"
    assert comparison["intersection"] == []


def test_back_to_back_confident_intervals_do_not_overlap(app):
    # In L each of 2152's periods ends exactly when 2151's begins, or begins
    # exactly when it ends: half-open intervals, so neither boundary is an overlap.
    comparison = compare(app, 2152, 2151)

    assert comparison["result"] == "separate"
    assert comparison["overlap_minutes"] == 0


def test_periods_without_am_pm_are_ambiguous_with_the_absence_noted(app):
    # B, Patrick Gittens on 7 October: "1030-1130" (row 33) and "730-830" (row 79).
    for excel_row, raw in ((33, "1030-1130"), (79, "730-830")):
        parse = time_parse(app, excel_row)

        assert parse["raw_time"]["value"] == raw
        assert parse["status"] == "ambiguous"
        [period] = parse["periods"]
        assert period["confidence"] == "ambiguous"
        assert period["interval"] is None
        assert period["plausible_reading"]["assumed"] is True
        assert any("AM/PM" in note for note in period["notes"])
        assert parse["confident_union"] == []

    assert time_parse(app, 33)["periods"][0]["plausible_reading"] == {"start": "10:30", "end": "11:30", "assumed": True}
    assert time_parse(app, 79)["periods"][0]["plausible_reading"] == {"start": "07:30", "end": "08:30", "assumed": True}


def test_the_plausible_reading_places_ambiguous_periods_in_the_afternoon_and_their_overlap_stays_assumed(app):
    # J, Orlando Richards on 6 October: "12:30-4:30" (row 61) and "11:30-4:30" (row 105).
    assert time_parse(app, 61)["periods"][0]["plausible_reading"] == {"start": "12:30", "end": "16:30", "assumed": True}
    assert time_parse(app, 105)["periods"][0]["plausible_reading"] == {"start": "11:30", "end": "16:30", "assumed": True}

    comparison = compare(app, 61, 105)
    assert comparison["result"] == "ambiguous"
    assert comparison["basis"] == "plausible_readings"
    assert comparison["assumed"] is True
    assert comparison["intersection"] == [{"start": "12:30", "end": "16:30"}]


def test_every_typed_time_cell_receives_a_status_and_raw_zero_is_zero_not_a_time(app):
    # Verified observation 20 in docs/decision-log.md: 132 integers, 4 floats and 2 datetimes.
    summary = app.get(f"/api/snapshots/{HANDOFF_WORKBOOK_SHA256}/time-parses").json()
    typed = {
        (group["raw_type"], group["status"]): group for group in summary["by_status"] if group["raw_type"] != "str"
    }

    assert {key: group["tickets"] for key, group in typed.items()} == {
        ("int", "zero_not_a_time"): 132,
        ("float", "number_not_a_time"): 4,
        ("datetime", "datetime_not_a_period"): 2,
    }
    assert sum(group["tickets"] for group in summary["by_status"]) == LAST_EXCEL_ROW - 1
    assert typed[("float", "number_not_a_time")]["excel_rows"] == [76, 77, 196, 197]
    assert typed[("datetime", "datetime_not_a_period")]["excel_rows"] == [56, 2511]

    zero = time_parse(app, 3)
    assert zero["raw_time"] == {"raw_type": "int", "value": 0}
    assert zero["periods"] == []
    assert "zero, not a time" in zero["notes"][0]
    assert time_parse(app, 76)["raw_time"] == {"raw_type": "float", "value": 730.43}
    assert time_parse(app, 56)["raw_time"] == {"raw_type": "datetime", "value": "2026-12-30T07:30:00"}


def test_reversed_implausible_and_possibly_overnight_periods_are_flagged_and_never_repaired(app):
    cases = {
        392: ("7:30pm-4:30pm", "reversed_endpoints"),
        321: ("8:00pm-6:00am", "possible_overnight"),
        224: ("12.00am 5:30pm", "implausible_duration"),  # 17.5 hours on one Date
        410: ("7:30am-11:30pm", "implausible_duration"),  # 16 hours, claiming 4 Regular Hours
    }
    for excel_row, (raw, flag) in cases.items():
        parse = time_parse(app, excel_row)

        assert parse["raw_time"]["value"] == raw
        assert parse["status"] == "flagged"
        [period] = parse["periods"]
        assert period["flags"] == [flag]
        assert period["interval"] is None
        assert period["plausible_reading"] is None
        assert parse["confident_union"] == []


def test_a_flagged_ticket_cannot_be_called_separate(app):
    # Row 321 (8pm to 6am) beside A's confident afternoon (row 591): nothing to compare against.
    comparison = compare(app, 321, 591)

    assert comparison["result"] == "undetermined"
    assert comparison["basis"] is None


def test_intersecting_confident_intervals_establish_overlap(app):
    # C, Peter Holder on 28 September: both rows read "7:30 am to 4:30 pm".
    comparison = compare(app, 620, 855)

    assert comparison["result"] == "overlap"
    assert comparison["basis"] == "confident_intervals"
    assert comparison["intersection"] == [{"start": "07:30", "end": "16:30"}]
    assert comparison["overlap_minutes"] == 9 * 60


def test_unknown_rows_and_comparisons_without_two_rows_are_refused(app):
    assert app.get(f"/api/snapshots/{HANDOFF_WORKBOOK_SHA256}/tickets/1/time").status_code == 404
    assert app.get(f"/api/snapshots/{'0' * 64}/tickets/620/time").status_code == 404
    assert app.get(f"/api/snapshots/{'0' * 64}/time-parses").status_code == 404

    comparison = f"/api/snapshots/{HANDOFF_WORKBOOK_SHA256}/time-comparison"
    assert app.get(comparison, params={"excel_row": [620, 2838]}).status_code == 404
    refused = app.get(comparison, params={"excel_row": [620]})
    assert refused.status_code == 422
    assert refused.json()["detail"]["field"] == "excel_row"


def test_an_ambiguous_period_ending_where_it_starts_is_flagged_rather_than_read_as_twelve_hours(app):
    # Row 144: "7.00 to 7.00". The end is not numerically below the start, so it is not taken as PM.
    parse = time_parse(app, 144)

    assert parse["status"] == "flagged"
    [period] = parse["periods"]
    assert period["confidence"] == "ambiguous"
    assert period["flags"] == ["implausible_duration"]
    assert period["plausible_reading"] is None
