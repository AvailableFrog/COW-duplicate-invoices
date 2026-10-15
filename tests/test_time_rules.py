"""Ticket #9: the Time-text variant, Work-period conflict and Ambiguous-period comparison rules.

Expected values come from the evidence report's examples A, G, J and L
(docs/source/labour-ticket-report-readable.md), PRD section 5 and section 12
criteria 4, 5 and 8. Shapes the export lacks are built with tests/synthetic.py.
"""

import json

from conftest import HANDOFF_WORKBOOK_SHA256, running
from synthetic import ticket, write_workbook

STRICT_FIELDS = [
    "Employee", "Date", "Job Number", "Time", "Regular Hours", "Overtime", "Double Time", "Job Work Pay",
]
NEW_RULES = ("time_text_variant", "work_period_conflict", "ambiguous_period_comparison")


def evidence(app, excel_row: int, fingerprint: str = HANDOFF_WORKBOOK_SHA256) -> dict:
    response = app.get(f"/api/snapshots/{fingerprint}/tickets/{excel_row}/possible-duplicate")
    assert response.status_code == 200, response.text
    return response.json()


def pair(app, first: int, second: int, fingerprint: str = HANDOFF_WORKBOOK_SHA256) -> dict:
    response = app.get(f"/api/snapshots/{fingerprint}/pairs/{first}/{second}")
    assert response.status_code == 200, response.text
    return response.json()


def candidates(payload: dict, rule_id: str) -> list[dict]:
    return [candidate for candidate in payload["candidates"] if candidate["rule_id"] == rule_id]


def member_rows(payload: dict) -> set[int]:
    return {member["excel_row"] for member in payload["members"]}


def verdict(explanation: dict, rule_id: str) -> dict:
    return next(rule for rule in explanation["rules"] if rule["rule_id"] == rule_id)


def fingerprint_of(booted) -> str:
    return booted.get("/api/snapshot").json()["snapshot_fingerprint"]


# G. Kerriann white, rows 82/103: "730am 430 pm" / "730 am 430 pm", every other claim field equal.
def test_g_is_a_time_text_variant_whose_reason_names_the_spacing_difference(app):
    g = evidence(app, 82)

    [variant] = candidates(g, "time_text_variant")
    assert variant["excel_rows"] == [82, 103]
    assert variant["rule_label"] == "Time-text variant"
    assert variant["fields_compared"] == STRICT_FIELDS
    assert variant["evidence_strength"] == "moderate"
    assert "spacing" in variant["reason"]
    # Both texts also read as the same Confident Interval, so that condition is disclosed too.
    assert "same work periods" in variant["reason"]
    assert "Same claim looks different as text" in g["pattern_labels"]
    assert candidates(g, "strict_repeat") == []


def test_a_time_text_variant_discloses_which_condition_matched(tmp_path):
    workbook = write_workbook(tmp_path / "variants.xlsx", [
        # Same Confident Interval written two ways: only the interval condition holds.
        ticket(1, Employee="Ann Smith", Time="7:30am-4:30pm"),
        ticket(2, Employee="Ann Smith", Time="0730 to 1630"),
        # Same tokens, different punctuation, no AM/PM: only the token condition holds.
        ticket(3, Employee="Bob Jones", Time="7:30-4:30"),
        ticket(4, Employee="Bob Jones", Time="7.30 - 4.30"),
        # Only the spaces around the dash moved.
        ticket(5, Employee="Cy Lee", Time="7:30am -4:30pm"),
        ticket(6, Employee="Cy Lee", Time="7:30am- 4:30pm"),
    ])

    with running(workbook, tmp_path) as booted:
        fingerprint = fingerprint_of(booted)
        intervals = candidates(evidence(booted, 2, fingerprint), "time_text_variant")
        tokens = candidates(evidence(booted, 4, fingerprint), "time_text_variant")
        moved = candidates(evidence(booted, 6, fingerprint), "time_text_variant")

    assert "same work periods" in intervals[0]["reason"] and "punctuation" not in intervals[0]["reason"]
    assert "punctuation" in tokens[0]["reason"] and "same work periods" not in tokens[0]["reason"]
    assert "differs only in spacing around" in moved[0]["reason"] and "punctuation" not in moved[0]["reason"]


# A. Romarian Alleyne, rows 591/593: "12:30 PM - 4:30 PM" (job 41215) / "7:30 AM - 11:30 AM" (job 20125), both 4 hours.
def test_a_is_explained_as_separate_work_with_no_candidate(app):
    a = pair(app, 591, 593)
    drawer = app.get(f"/api/snapshots/{HANDOFF_WORKBOOK_SHA256}/tickets/591/possible-duplicate")

    assert drawer.status_code == 404
    assert a["excel_rows"] == [591, 593]
    assert a["linked"] is False
    assert a["same_employee_and_date"] is True
    assert a["time_comparison"]["result"] == "separate"
    assert a["time_comparison"]["intersection"] == []
    conflict = verdict(a, "work_period_conflict")
    assert conflict["matched"] is False
    assert "separate" in conflict["reason"]
    assert all(rule["matched"] is False for rule in a["rules"])
    assert "separate work periods" in a["summary"]
    assert "equal hours" in a["summary"].lower()
    assert [member["excel_row"] for member in a["members"]] == [591, 593]
    assert [member["time_parse"]["status"] for member in a["members"]] == ["confident", "confident"]


# L. Weston Holder, rows 2151/2152: "1030am 230pm" against "730am 1030am _ 230pm 430pm".
def test_l_has_no_work_period_conflict_across_the_middle_gap(app):
    l_pair = pair(app, 2151, 2152)

    assert l_pair["linked"] is False
    assert l_pair["time_comparison"]["result"] == "separate"
    assert verdict(l_pair, "work_period_conflict")["matched"] is False
    response = app.get(f"/api/snapshots/{HANDOFF_WORKBOOK_SHA256}/tickets/2152/possible-duplicate")
    if response.status_code == 200:
        assert 2151 not in member_rows(response.json())


# J. Orlando Richards, rows 61/105: "12:30-4:30" / "11:30-4:30", job 41202, 4 hours each, no AM/PM.
def test_j_is_an_ambiguous_period_comparison_showing_the_assumed_afternoon_overlap_without_asserting_it(app):
    j = evidence(app, 61)

    [comparison] = candidates(j, "ambiguous_period_comparison")
    assert comparison["excel_rows"] == [61, 105]
    assert comparison["rule_label"] == "Ambiguous-period comparison"
    assert comparison["evidence_strength"] == "weak"
    assert set(STRICT_FIELDS) - {"Time"} <= set(comparison["fields_compared"])
    times = comparison["time_comparison"]
    assert times["result"] == "ambiguous"
    assert times["assumed"] is True
    assert times["intersection"] == [{"start": "12:30", "end": "16:30"}]
    assert "assumed" in comparison["reason"]
    assert "cannot be established" in comparison["reason"]
    assert candidates(j, "work_period_conflict") == []
    plausible = [period["plausible_reading"] for m in j["members"] for period in m["time_parse"]["periods"]]
    assert all(reading["assumed"] is True for reading in plausible)
    # An assumed overlap is never labelled as separate work.
    assert j["pattern_labels"] == ["Possible correction or resubmission"]


# B. Patrick Gittens, rows 33/79: "1030-1130" / "730-830", job 20105, one hour each, no AM/PM.
def test_b_is_an_ambiguous_period_comparison_whose_assumed_readings_do_not_overlap(app):
    b = evidence(app, 33)

    [comparison] = candidates(b, "ambiguous_period_comparison")
    assert comparison["time_comparison"]["result"] == "ambiguous"
    assert comparison["time_comparison"]["intersection"] == []
    assert "would not overlap" in comparison["reason"] and "assumed" in comparison["reason"]
    assert b["pattern_labels"] == ["Equal duration, separate periods"]


def test_orlandos_morning_hr_ticket_at_row_137_is_not_in_js_possible_duplicate(app):
    j = evidence(app, 105)

    assert member_rows(j) == {61, 105}
    explanation = pair(app, 105, 137)
    assert explanation["same_employee_and_date"] is True
    assert explanation["linked"] is False


def test_a_work_period_conflict_is_found_across_different_jobs_when_confident_intervals_intersect(tmp_path):
    workbook = write_workbook(tmp_path / "conflict.xlsx", [
        ticket(1, Employee="Ann Smith", Job_Number=41215, Time="7:30am-12:30pm", Regular_Hours=5),
        ticket(2, Employee="ann  SMITH", Job_Number=20105, Time="11:30am-4:30pm", Regular_Hours=5, Overtime=1),
        # Another employee working the same hours is never compared.
        ticket(3, Employee="Bob Jones", Job_Number=20105, Time="11:30am-4:30pm"),
    ])

    with running(workbook, tmp_path) as booted:
        payload = evidence(booted, 2, fingerprint_of(booted))

    assert member_rows(payload) == {2, 3}
    [conflict] = payload["candidates"]
    assert conflict["rule_id"] == "work_period_conflict"
    assert conflict["rule_label"] == "Work-period conflict"
    assert conflict["fields_compared"] == ["Employee", "Date", "Time"]
    assert conflict["time_comparison"]["result"] == "overlap"
    assert conflict["time_comparison"]["intersection"] == [{"start": "11:30", "end": "12:30"}]
    assert "conflicting work claim" in conflict["reason"]
    assert "different jobs" in conflict["reason"]
    assert payload["pattern_labels"] == ["Possible correction or resubmission"]


def test_equal_hours_on_the_same_day_never_link_tickets_on_their_own(tmp_path):
    workbook = write_workbook(tmp_path / "equal-hours.xlsx", [
        # Like A: separate confident periods on different jobs.
        ticket(1, Employee="Ann Smith", Job_Number=41215, Time="12:30 PM - 4:30 PM", Regular_Hours=4),
        ticket(2, Employee="Ann Smith", Job_Number=20125, Time="7:30 AM - 11:30 AM", Regular_Hours=4),
        # Like J and row 137: no AM/PM, same hours, but different jobs.
        ticket(3, Employee="Bob Jones", Job_Number=41202, Time="12:30-4:30", Regular_Hours=4),
        ticket(4, Employee="Bob Jones", Job_Number=20125, Time="7:30-11:30", Regular_Hours=4),
    ])

    with running(workbook, tmp_path) as booted:
        found = booted.get("/api/review-priorities").json()["possible_duplicates"]

    assert found == []


def test_an_ambiguous_period_comparison_needs_a_nonzero_job(tmp_path):
    workbook = write_workbook(tmp_path / "job-zero.xlsx", [
        ticket(1, Employee="Ann Smith", Job_Number=0, Time="12:30-4:30", Regular_Hours=4),
        ticket(2, Employee="Ann Smith", Job_Number=0, Time="11:30-4:30", Regular_Hours=4),
        ticket(3, Employee="Bob Jones", Job_Number=41202, Time="12:30-4:30", Regular_Hours=4),
        ticket(4, Employee="Bob Jones", Job_Number=41202, Time="11:30-4:30", Regular_Hours=4),
    ])

    with running(workbook, tmp_path) as booted:
        found = booted.get("/api/review-priorities").json()["possible_duplicates"]

    assert [(item["rule_ids"], sorted(m["excel_row"] for m in item["members"])) for item in found] == [
        (["ambiguous_period_comparison"], [4, 5]),
    ]


def test_a_three_ticket_possible_duplicate_shows_both_overlap_edges_and_calls_no_ticket_redundant(tmp_path):
    workbook = write_workbook(tmp_path / "three.xlsx", [
        ticket(1, Employee="Ann Smith", Job_Number=41215, Time="7:30am-4:30pm", Regular_Hours=8),
        ticket(2, Employee="Ann Smith", Job_Number=20105, Time="7:30am-11:30am", Regular_Hours=4),
        ticket(3, Employee="Ann Smith", Job_Number=20125, Time="12:30pm-4:30pm", Regular_Hours=4),
    ])

    with running(workbook, tmp_path) as booted:
        fingerprint = fingerprint_of(booted)
        drawer = evidence(booted, 3, fingerprint)
        listed = booted.get("/api/review-priorities").json()["possible_duplicates"]
        morning_afternoon = pair(booted, 3, 4, fingerprint)

    assert member_rows(drawer) == {2, 3, 4}
    assert [(c["excel_rows"], c["rule_id"]) for c in drawer["candidates"]] == [
        ([2, 3], "work_period_conflict"),
        ([2, 4], "work_period_conflict"),
    ]
    assert [c["time_comparison"]["intersection"] for c in drawer["candidates"]] == [
        [{"start": "07:30", "end": "11:30"}],
        [{"start": "12:30", "end": "16:30"}],
    ]
    # The morning and afternoon tickets are separate work and are not linked to each other.
    assert morning_afternoon["linked"] is False
    assert morning_afternoon["time_comparison"]["result"] == "separate"
    assert "need not repeat" in drawer["reason"]
    assert len(listed) == 1 and listed[0]["exact_repeat_not_flagged"] is False
    text = json.dumps([drawer, listed]).casefold()
    assert "redundant" not in text and "n - 1" not in text and "survivor" not in text


def test_a_pair_matched_by_several_rules_carries_one_candidate_per_rule_and_shows_every_reason(app):
    # G: a Time-text variant whose texts both read 07:30-16:30, so its work periods also overlap.
    g = evidence(app, 103)
    # C. Peter Holder: a strict repeat whose identical confident times also overlap.
    peter = evidence(app, 620)

    assert sorted(c["rule_id"] for c in g["candidates"]) == ["time_text_variant", "work_period_conflict"]
    assert sorted(c["rule_id"] for c in peter["candidates"]) == ["strict_repeat", "work_period_conflict"]
    for payload in (g, peter):
        assert {tuple(c["excel_rows"]) for c in payload["candidates"]} == {tuple(sorted(member_rows(payload)))}
        for candidate in payload["candidates"]:
            assert candidate["fields_compared"] and candidate["evidence_strength"] and candidate["reason"]
        assert len(payload["review"]["pairs"]) == 1
        assert sorted(payload["review"]["pairs"][0]["rule_ids"]) == sorted(c["rule_id"] for c in payload["candidates"])
    assert "Same claim with the time written differently" in g["reason"] and "Times overlap" in g["reason"]
    assert "Same claim submitted twice" in peter["reason"] and "Times overlap" in peter["reason"]


def test_the_pair_explanation_gives_every_rules_verdict_for_a_linked_pair(app):
    peter = pair(app, 855, 620)

    assert peter["excel_rows"] == [620, 855]
    assert peter["linked"] is True
    assert [rule["rule_id"] for rule in peter["rules"]] == [
        "strict_repeat", "time_text_variant", "work_period_conflict", "ambiguous_period_comparison",
    ]
    assert [rule["matched"] for rule in peter["rules"]] == [True, False, True, False]
    assert all(rule["reason"] for rule in peter["rules"])
    assert peter["possible_duplicate"] == "Possible duplicate L225526+L225761"


def test_the_pair_explanation_refuses_one_row_and_unknown_rows(app):
    base = f"/api/snapshots/{HANDOFF_WORKBOOK_SHA256}/pairs"

    assert app.get(f"{base}/591/591").status_code == 422
    assert app.get(f"{base}/591/9999").status_code == 404
    assert app.get(f"/api/snapshots/{'0' * 64}/pairs/591/593").status_code == 404


def test_pairs_outside_the_employee_and_date_search_space_are_never_compared(app):
    # Peter Holder (620) and Latoya Small (974): different employees.
    explanation = pair(app, 620, 974)

    assert explanation["same_employee_and_date"] is False
    assert explanation["linked"] is False
    assert all(rule["matched"] is False for rule in explanation["rules"])


def test_every_rule_is_described_with_its_fields_strength_and_pattern(app):
    rules = {rule["id"]: rule for rule in app.get("/api/review-priorities").json()["rules"]}

    assert list(rules) == ["strict_repeat", *NEW_RULES]
    assert rules["time_text_variant"]["pattern"] == "Same claim looks different as text"
    assert rules["work_period_conflict"]["fields_compared"] == ["Employee", "Date", "Time"]
    assert rules["ambiguous_period_comparison"]["evidence_strength"] == "weak"
    assert all(rule["reason"] and rule["label"] for rule in rules.values())


def test_the_new_rules_join_the_ranked_list_and_c_to_f_still_lead(app):
    body = app.get("/api/review-priorities").json()
    ranked = body["possible_duplicates"]
    tiles = {tile["metric_id"]: tile for tile in app.get("/api/overview/tiles").json()["tiles"]}

    assert [{m["excel_row"] for m in item["members"]} for item in ranked[:4]] == [
        {2206, 2351}, {974, 1868}, {1309, 1656}, {620, 855},
    ]
    assert [item["exact_repeat_not_flagged"] for item in ranked].count(True) == 4
    exact = tiles["unflagged_exact_repeat_count"]
    assert (exact["value"], exact["tickets"]) == (4, 8)
    found = {rule for item in ranked for rule in item["rule_ids"]}
    assert set(NEW_RULES) <= found
    # Possible duplicates stay disjoint however many rules link their tickets.
    rows = [m["excel_row"] for item in ranked for m in item["members"]]
    assert len(rows) == len(set(rows))
    assert [item["tier"]["rank"] for item in ranked] == sorted(item["tier"]["rank"] for item in ranked)


def test_c_to_f_read_only_as_the_same_claim_appearing_twice_though_their_times_also_overlap(app):
    # C, D, E and F: each pair also carries a Work-period conflict Candidate, labelled with the repeat's pattern.
    for row in (620, 974, 1309, 2206):
        payload = evidence(app, row)
        assert sorted(c["rule_id"] for c in payload["candidates"]) == ["strict_repeat", "work_period_conflict"]
        assert payload["pattern_labels"] == ["Same claim appears twice"]
        assert {c["pattern"] for c in payload["candidates"]} == {"Same claim appears twice"}
    # G: a time-text variant's overlap belongs to that pattern too.
    assert evidence(app, 82)["pattern_labels"] == ["Same claim looks different as text"]
