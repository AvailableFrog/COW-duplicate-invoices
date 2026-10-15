"""Ticket #14: the pattern-by-source-state matrix and the multi-label pattern filter on Review priorities."""

from conftest import running
from synthetic import ticket, write_workbook

STATES = ["approved_keyed", "approved_not_keyed", "pending", "rejected", "flagged_duplicate", "unreadable"]
PATTERNS = [
    ("same_claim_twice", 1, "Same claim appears twice"),
    ("same_claim_as_different_text", 2, "Same claim looks different as text"),
    ("correction_or_resubmission", 3, "Possible correction or resubmission"),
    ("equal_duration_separate_periods", 4, "Equal duration, separate periods"),
    ("repeated_payment_component", 5, "Repeated payment component"),
]
H_ROWS = {829, 1072}
I_ROWS = {318, 999, 1545}


def priorities(app, **params) -> dict:
    response = app.get("/api/review-priorities", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def member_rows(item: dict) -> set[int]:
    return {member["excel_row"] for member in item["members"]}


def by_rows(body: dict, rows: set[int]) -> dict:
    return next(item for item in body["possible_duplicates"] if member_rows(item) == rows)


def cells(row: dict) -> dict[str, int]:
    return {cell["source_state"]: cell["tickets"] for cell in row["cells"]}


def metric(app, metric_id: str, **params) -> int:
    response = app.get(f"/api/metrics/{metric_id}", params=params)
    assert response.status_code == 200, response.text
    return response.json()["value"]


def test_the_matrix_has_a_row_per_pattern_a_column_per_source_state_and_a_caption_saying_counts_overlap(app):
    matrix = priorities(app)["pattern_matrix"]

    assert [(r["pattern"]["id"], r["pattern"]["number"], r["pattern"]["label"]) for r in matrix["rows"]] == PATTERNS
    assert [state["id"] for state in matrix["source_states"]] == STATES
    assert [state["label"] for state in matrix["source_states"]][:5] == [
        "Approved, Keyed", "Approved, not Keyed", "Pending", "Rejected", "Flagged duplicate",
    ]
    assert all([cell["source_state"] for cell in row["cells"]] == STATES for row in matrix["rows"])
    assert matrix["grain"] == "Ticket"
    assert "overlap" in matrix["caption"]
    assert "do not add up" in matrix["note"]


def test_a_pattern_row_splits_its_tickets_by_state_but_the_rows_overlap_and_only_the_union_reconciles(app):
    body = priorities(app)
    matrix = body["pattern_matrix"]

    # Each Ticket has one source state, so a row's cells add up to its own Ticket count...
    assert all(sum(cells(row).values()) == row["tickets"] for row in matrix["rows"])
    assert sum(cells(matrix["any_pattern"]).values()) == matrix["any_pattern"]["tickets"]
    # ...but one Ticket or possible duplicate can carry several patterns, so the rows add up to more than the union,
    # which is the registry's candidate_ticket_count and the length of the list.
    assert matrix["any_pattern"]["tickets"] == metric(app, "candidate_ticket_count") == 186
    assert matrix["any_pattern"]["possible_duplicates"] == len(body["possible_duplicates"]) == 85
    assert sum(row["tickets"] for row in matrix["rows"]) > matrix["any_pattern"]["tickets"]
    assert sum(row["possible_duplicates"] for row in matrix["rows"]) > matrix["any_pattern"]["possible_duplicates"]
    for state in STATES:
        assert sum(cells(row)[state] for row in matrix["rows"]) >= cells(matrix["any_pattern"])[state]


def test_the_same_claim_row_holds_the_34_strict_groups_and_their_published_states(app):
    rows = {row["pattern"]["id"]: row for row in priorities(app)["pattern_matrix"]["rows"]}
    same_claim = rows["same_claim_twice"]

    # 34 two-ticket groups, no Ticket in two (PRD section 5); C-F's 8 Approved and Keyed Tickets among them; the
    # Pending/Pending and Approved/Pending groups and Pending/Rejected rows 96/799 (decision-log entry 27) give 4 Pending.
    assert (same_claim["possible_duplicates"], same_claim["tickets"]) == (34, 68)
    assert cells(same_claim)["approved_keyed"] >= 8
    assert cells(same_claim)["pending"] == 4
    assert cells(same_claim)["flagged_duplicate"] == 0
    # I's flagged row 318 is linked only as a possible correction, never as the same claim (decision-log entry 52).
    assert cells(rows["correction_or_resubmission"])["flagged_duplicate"] >= 1


def test_every_matrix_cell_drills_down_to_a_list_whose_ticket_total_is_the_cell(app):
    matrix = priorities(app)["pattern_matrix"]

    for row in matrix["rows"]:
        pattern = row["pattern"]["id"]
        for state, count in cells(row).items():
            if count == 0:
                continue
            body = priorities(app, pattern=pattern, source_state=state)
            selected = [m for item in body["possible_duplicates"] for m in item["members"] if m["in_selection"]]
            assert body["pattern_filter"]["totals"]["tickets"] == count == len({m["excel_row"] for m in selected})
            assert {m["source_state"] for m in selected} == {state}
            assert all(pattern in item["pattern_ids"] for item in body["possible_duplicates"])
        whole_row = priorities(app, pattern=pattern)["pattern_filter"]["totals"]
        assert (whole_row["possible_duplicates"], whole_row["tickets"]) == (row["possible_duplicates"], row["tickets"])


def test_two_pattern_filters_list_possible_duplicates_matching_either_with_union_totals_no_larger_than_the_sum(app):
    everything = priorities(app)["possible_duplicates"]
    body = priorities(app, pattern=["same_claim_twice", "correction_or_resubmission"])
    listed = body["possible_duplicates"]
    pattern_filter = body["pattern_filter"]
    counts = {count["id"]: count for count in pattern_filter["counts"]}
    chosen = [counts["same_claim_twice"], counts["correction_or_resubmission"]]

    assert pattern_filter["patterns"] == ["same_claim_twice", "correction_or_resubmission"]
    assert [count["selected"] for count in pattern_filter["counts"]] == [True, False, True, False, False]
    assert {item["display_id"] for item in listed} == {
        item["display_id"] for item in everything
        if {"Same claim appears twice", "Possible correction or resubmission"} & set(item["pattern_labels"])
    }
    assert [item["rank"] for item in listed] == list(range(1, len(listed) + 1))
    totals = pattern_filter["totals"]
    assert totals["possible_duplicates"] == len(listed)
    assert totals["tickets"] == len({m["excel_row"] for item in listed for m in item["members"] if m["in_selection"]})
    assert totals["possible_duplicates"] <= sum(count["possible_duplicates"] for count in chosen)
    assert totals["tickets"] <= sum(count["tickets"] for count in chosen)
    # I (318/999/1545) carries both patterns and is one possible duplicate, so the union is strictly smaller.
    assert sum(1 for item in listed if member_rows(item) == I_ROWS) == 1
    assert totals["possible_duplicates"] < sum(count["possible_duplicates"] for count in chosen)
    assert "overlap" in pattern_filter["note"]


def test_a_pattern_filter_keeps_every_member_and_marks_those_no_selected_pattern_links(app):
    body = priorities(app, pattern="same_claim_twice")
    i = by_rows(body, I_ROWS)

    # 318 is linked only by the Flagged-duplicate counterpart and Work-period conflict, both pattern 3.
    assert {m["excel_row"]: m["in_selection"] for m in i["members"]} == {1545: True, 999: True, 318: False}
    assert all(m["in_filter"] for m in i["members"])
    # The matrix ignores the pattern filter: it is what the filter is chosen from.
    assert body["pattern_matrix"] == priorities(app)["pattern_matrix"]


def test_with_status_pending_h_keeps_its_approved_member_labelled_outside_and_aggregates_count_only_pending(app):
    body = priorities(app, status="Pending")
    h = by_rows(body, H_ROWS)
    tiles = {tile["metric_id"]: tile for tile in app.get("/api/overview/tiles", params={"status": "Pending"}).json()["tiles"]}
    matrix = body["pattern_matrix"]

    assert {m["excel_row"]: (m["status"], m["in_filter"]) for m in h["members"]} == {
        1072: ("Pending", True), 829: ("Approved", False),
    }
    assert {m["excel_row"]: m["in_selection"] for m in h["members"]} == {1072: True, 829: False}
    # The tiles count in-filter Tickets only: 129 Pending, and nothing Approved.
    assert (tiles["ticket_count"]["value"], tiles["pending_count"]["value"]) == (129, 129)
    assert (tiles["flagged_duplicate_count"]["value"], tiles["approved_not_keyed_count"]["value"]) == (0, 0)
    assert tiles["unflagged_exact_repeat_count"]["value"] == 0
    # So does the matrix: H's Approved row 829 is shown for comparison, never counted.
    for row in [*matrix["rows"], matrix["any_pattern"]]:
        assert {state for state, n in cells(row).items() if n} <= {"pending"}
    assert matrix["any_pattern"]["tickets"] == metric(app, "candidate_ticket_count", status="Pending")
    assert body["pattern_filter"]["totals"]["tickets"] == matrix["any_pattern"]["tickets"]


def test_a_possible_duplicate_with_mixed_statuses_keeps_its_member_level_breakdown(app):
    body = priorities(app)
    h = by_rows(body, H_ROWS)
    i = by_rows(body, I_ROWS)

    assert h["source_states"] == [
        {"id": "approved_keyed", "label": "Approved, Keyed", "tickets": 1},
        {"id": "pending", "label": "Pending", "tickets": 1},
    ]
    assert [(s["id"], s["tickets"]) for s in i["source_states"]] == [
        ("approved_keyed", 1), ("rejected", 1), ("flagged_duplicate", 1),
    ]
    assert {m["excel_row"]: m["source_state"] for m in i["members"]} == {
        1545: "approved_keyed", 999: "rejected", 318: "flagged_duplicate",
    }
    assert h["pattern_ids"] == ["same_claim_as_different_text"]


def test_an_unknown_pattern_or_source_state_is_refused(app):
    for params, field in (({"pattern": "fraud"}, "pattern"), ({"source_state": "paid"}, "source_state")):
        response = app.get("/api/review-priorities", params=params)
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert (detail["code"], detail["field"]) == ("invalid_filter", field)
        assert "same_claim_twice" in detail["message"] or "approved_keyed" in detail["message"]


def test_a_ticket_with_an_unreadable_keyed_falls_in_its_own_column_and_a_flagged_one_only_in_flagged(tmp_path):
    workbook = write_workbook(tmp_path / "states.xlsx", [
        ticket(1, Employee="Ann Smith"),
        ticket(2, Employee="Ann Smith", Keyed=None),
        ticket(3, Employee="Bob Jones", Job_Number=0),
        ticket(4, Employee="Bob Jones", Job_Number=0),
    ])

    with running(workbook, tmp_path) as booted:
        matrix = priorities(booted)["pattern_matrix"]

    same_claim = cells(next(row for row in matrix["rows"] if row["pattern"]["id"] == "same_claim_twice"))
    assert same_claim == {
        "approved_keyed": 1, "approved_not_keyed": 0, "pending": 0, "rejected": 0, "flagged_duplicate": 2,
        "unreadable": 1,
    }
