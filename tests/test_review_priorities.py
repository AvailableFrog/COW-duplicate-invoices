"""Ticket #6: the Strict repeat rule, Possible Duplicates and the ranked Review priorities list."""

import datetime as dt
from collections import Counter

from conftest import WORKBOOK, running
from synthetic import ticket, write_workbook


def priorities(app, **params) -> dict:
    response = app.get("/api/review-priorities", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def member_states(possible_duplicate: dict) -> tuple[str, ...]:
    return tuple(sorted(member["status"] for member in possible_duplicate["members"]))


def test_the_strict_repeat_rule_finds_34_two_ticket_possible_duplicates_with_the_published_source_states(app):
    found = [item for item in priorities(app)["possible_duplicates"] if "strict_repeat" in item["rule_ids"]]

    assert len(found) == 34
    assert all(len(item["members"]) == 2 for item in found)
    approved_keyed_nonzero = [
        item for item in found
        if all(m["status"] == "Approved" and m["keyed"] is True and m["job_number"] != 0 for m in item["members"])
    ]
    with_rejected = [item for item in found if "Rejected" in member_states(item)]
    assert len(approved_keyed_nonzero) == 4
    assert len(with_rejected) == 28
    assert Counter(member_states(item) for item in found if item not in approved_keyed_nonzero + with_rejected) == {
        ("Pending", "Pending"): 1,
        ("Approved", "Pending"): 1,
    }


def member_rows(possible_duplicate: dict) -> set[int]:
    return {member["excel_row"] for member in possible_duplicate["members"]}


def test_the_four_unflagged_approved_keyed_exact_repeats_lead_the_list_oldest_created_first(app):
    ranked = priorities(app)["possible_duplicates"]

    # C-F, ordered by each pair's earliest Created: F 13 Sep, D 20 Sep, E 21 Sep, C 28 Sep.
    assert [member_rows(item) for item in ranked[:4]] == [{2206, 2351}, {974, 1868}, {1309, 1656}, {620, 855}]
    assert {item["tier"]["rank"] for item in ranked[:4]} == {1}
    # The label agrees with the tile of the same name: only these four carry it.
    assert [item["exact_repeat_not_flagged"] for item in ranked] == [True] * 4 + [False] * (len(ranked) - 4)
    assert [item["rank"] for item in ranked] == list(range(1, len(ranked) + 1))


def test_mixed_approved_and_pending_comes_next_then_pending_conflicts_then_rejected_members(app):
    ranked = priorities(app)["possible_duplicates"]

    assert member_rows(ranked[4]) == {425, 1191}
    assert ranked[4]["tier"]["rank"] == 2
    assert member_rows(ranked[5]) == {84, 88}
    assert ranked[5]["tier"]["rank"] == 3
    assert all("Rejected" in member_states(item) and item["tier"]["rank"] == 4 for item in ranked[6:])
    tier_four_created = [min(m["created"] for m in item["members"]) for item in ranked[6:]]
    assert tier_four_created == sorted(tier_four_created)


STRICT_FIELDS = [
    "Employee", "Date", "Job Number", "Time", "Regular Hours", "Overtime", "Double Time", "Job Work Pay",
]


def by_rows(app, *rows: int) -> dict:
    return next(item for item in priorities(app)["possible_duplicates"] if member_rows(item) == set(rows))


def test_the_peter_holder_possible_duplicate_is_named_by_its_sorted_ticket_numbers(app):
    peter = by_rows(app, 620, 855)

    assert peter["display_id"] == "Possible duplicate L225526+L225761"
    assert [member["ticket_number"] for member in peter["members"]] == ["L225526", "L225761"]
    assert {member["employee"] for member in peter["members"]} == {"Peter Holder"}


def test_every_candidate_carries_its_rule_fields_compared_evidence_strength_and_reason(app):
    ranked = priorities(app)["possible_duplicates"]
    peter = by_rows(app, 620, 855)

    assert peter["candidates"] == [
        {
            "excel_rows": [620, 855],
            "rule_id": "strict_repeat",
            "fields_compared": STRICT_FIELDS,
            "evidence_strength": "strong",
            "reason": peter["candidates"][0]["reason"],
            # Ticket #8: each pair's Review Outcome rides along for display; nothing is saved in this session.
            "outcome": {"id": "not_reviewed", "label": "Not reviewed"},
        }
    ]
    assert "Same claim submitted twice" in peter["candidates"][0]["reason"]
    assert all(candidate["reason"] and candidate["fields_compared"] for item in ranked for candidate in item["candidates"])


def test_each_row_shows_pattern_labels_an_evidence_summary_and_member_source_states(app):
    peter = by_rows(app, 620, 855)

    assert peter["pattern_labels"] == ["Same claim appears twice"]
    assert "Same claim submitted twice" in peter["summary"]
    assert [
        (m["excel_row"], m["status"], m["keyed"], m["job_number"], m["flagged_duplicate"]) for m in peter["members"]
    ] == [(855, "Approved", True, 41215, False), (620, "Approved", True, 41215, False)]


def test_a_blank_or_invalid_claim_component_never_forms_a_strict_group(tmp_path):
    workbook = write_workbook(tmp_path / "strict.xlsx", [
        ticket(1, Employee="Ann Smith"),
        ticket(2, Employee="  ann   SMITH "),
        ticket(3, Employee="Bob Jones", Overtime=None),
        ticket(4, Employee="Bob Jones", Overtime=None),
        ticket(5, Employee="Cy Lee", Job_Work_Pay="n/a"),
        ticket(6, Employee="Cy Lee", Job_Work_Pay="n/a"),
    ])

    with running(workbook, tmp_path) as booted:
        found = priorities(booted)["possible_duplicates"]

    assert [member_rows(item) for item in found] == [{2, 3}]


def test_tickets_differing_only_outside_the_strict_key_still_match_and_ties_break_on_lowest_ticket_number(tmp_path):
    workbook = write_workbook(tmp_path / "ties.xlsx", [
        ticket(1, Employee="Ann Smith", Ticket_Number="L000050"),
        ticket(2, Employee="Ann Smith", Ticket_Number="L000060"),
        ticket(3, Employee="Dee Ray", Ticket_Number="L000070"),
        ticket(
            4, Employee="Dee Ray", Ticket_Number="L000010", Supervisor="Supervisor B",
            Description_of_Job_Work="Different words", Created=dt.datetime(2026, 10, 3, 9, 0),
        ),
    ])

    with running(workbook, tmp_path) as booted:
        found = priorities(booted)["possible_duplicates"]

    # Both pairs' oldest Created is 2 Oct 18:56, so the lowest Ticket Number (L000010) decides.
    assert [item["display_id"] for item in found] == [
        "Possible duplicate L000010+L000070",
        "Possible duplicate L000050+L000060",
    ]


def test_the_exact_repeat_tile_counts_four_possible_duplicates_and_shows_their_eight_tickets(app):
    tiles = {tile["metric_id"]: tile for tile in app.get("/api/overview/tiles").json()["tiles"]}
    metric = app.get("/api/metrics/unflagged_exact_repeat_count", params={"rows": "true"}).json()

    tile = tiles["unflagged_exact_repeat_count"]
    assert (tile["label"], tile["value"], tile["tickets"], tile["unit"]) == (
        "Exact repeats, not flagged", 4, 8, "possible duplicates",
    )
    assert metric["availability"]["status"] == "available"
    assert metric["contributing_rows"] == [620, 855, 974, 1309, 1656, 1868, 2206, 2351]


def test_a_filter_selects_a_possible_duplicate_when_one_member_matches_and_labels_the_others(app):
    peter_job = app.get("/api/metrics/unflagged_exact_repeat_count", params={"job": 41215}).json()
    pending = app.get("/api/metrics/unflagged_exact_repeat_count", params={"status": "Pending"}).json()
    rommell = [
        item for item in priorities(app, status="Pending")["possible_duplicates"] if member_rows(item) == {425, 1191}
    ]

    assert (peter_job["value"], peter_job["tickets"]) == (1, 2)
    assert pending["value"] == 0
    assert [(m["excel_row"], m["in_filter"]) for m in rommell[0]["members"]] == [(1191, False), (425, True)]


def test_responses_carry_the_rule_version_and_describe_each_rule(app):
    body = priorities(app)
    tiles = app.get("/api/overview/tiles").json()

    assert body["versions"]["rules"] != "0.0.0"
    assert tiles["versions"]["rules"] == body["versions"]["rules"]
    assert [rule["id"] for rule in body["rules"]] == ["strict_repeat"]
    assert body["rules"][0]["fields_compared"] == STRICT_FIELDS
    assert [tier["rank"] for tier in body["tiers"]] == [1, 2, 3, 4]


def test_the_ranked_order_is_identical_across_two_runs(app, tmp_path):
    first = priorities(app)

    with running(WORKBOOK, tmp_path) as second_run:
        second = priorities(second_run)

    assert [item["display_id"] for item in second["possible_duplicates"]] == [
        item["display_id"] for item in first["possible_duplicates"]
    ]
    assert second["possible_duplicates"] == first["possible_duplicates"]
