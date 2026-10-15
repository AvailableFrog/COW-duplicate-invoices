"""Ticket #10: the Name-space variant rule and reviewer-confirmed Aliases.

Expected values come from the evidence report's examples F and H
(docs/source/labour-ticket-report-readable.md), PRD section 5 ("Identity" and
the conservative predicates) and the raw workbook. A confirmed Alias widens
the employee key only for the rules that accept one; shapes the export lacks
are built with tests/synthetic.py.
"""

import datetime as dt

import duckdb
import pytest

from conftest import HANDOFF_WORKBOOK_SHA256, WORKBOOK, running
from synthetic import ticket, write_workbook

MARIO = ["mario collymore", "mariocollymore"]
STRICT_FIELDS = [
    "Employee", "Date", "Job Number", "Time", "Regular Hours", "Overtime", "Double Time", "Job Work Pay",
]


def evidence(app, excel_row: int, fingerprint: str = HANDOFF_WORKBOOK_SHA256) -> dict:
    response = app.get(f"/api/snapshots/{fingerprint}/tickets/{excel_row}/possible-duplicate")
    assert response.status_code == 200, response.text
    return response.json()


def pair(app, first: int, second: int, fingerprint: str = HANDOFF_WORKBOOK_SHA256) -> dict:
    response = app.get(f"/api/snapshots/{fingerprint}/pairs/{first}/{second}")
    assert response.status_code == 200, response.text
    return response.json()


def verdict(explanation: dict, rule_id: str) -> dict:
    return next(rule for rule in explanation["rules"] if rule["rule_id"] == rule_id)


def rule_ids(payload: dict) -> list[str]:
    return sorted(candidate["rule_id"] for candidate in payload["candidates"])


def member_rows(payload: dict) -> set[int]:
    return {member["excel_row"] for member in payload["members"]}


def fingerprint_of(booted) -> str:
    return booted.get("/api/snapshot").json()["snapshot_fingerprint"]


def aliases(app, fingerprint: str = HANDOFF_WORKBOOK_SHA256) -> list[dict]:
    response = app.get(f"/api/snapshots/{fingerprint}/aliases")
    assert response.status_code == 200, response.text
    return response.json()["aliases"]


def decide(app, labels: list[str], decision: str, fingerprint: str = HANDOFF_WORKBOOK_SHA256, **body):
    payload = {"labels": labels, "decision": decision, "reviewer": "Test reviewer", "rationale": "Checked", **body}
    return app.client.put(f"/api/snapshots/{fingerprint}/aliases", json=payload)


def decided(app, labels: list[str], decision: str, fingerprint: str = HANDOFF_WORKBOOK_SHA256, **body) -> dict:
    response = decide(app, labels, decision, fingerprint, **body)
    assert response.status_code == 200, response.text
    return response.json()


def label_count(app) -> int:
    response = app.get("/api/metrics/employee_label_count")
    assert response.status_code == 200, response.text
    return response.json()["value"]


# H. Mario Collymore / Mariocollymore, rows 829/1072, 23 September: every claim field equal but the name.
def test_h_is_a_name_space_variant_proposing_the_alias_mario_collymore_mariocollymore(app):
    h = evidence(app, 1072)

    assert member_rows(h) == {829, 1072}
    assert rule_ids(h) == ["name_space_variant"]
    [candidate] = h["candidates"]
    assert candidate["excel_rows"] == [829, 1072]
    assert candidate["rule_label"] == "Name-space variant"
    assert candidate["fields_compared"] == STRICT_FIELDS
    assert candidate["evidence_strength"] == "moderate"
    assert candidate["pattern"] == "Same claim looks different as text"
    assert "Mario Collymore" in candidate["reason"] and "Mariocollymore" in candidate["reason"]
    assert "Alias" in candidate["reason"]
    assert h["pattern_labels"] == ["Same claim looks different as text"]
    # The labels are not merged: each member keeps its own name, and the proposal waits for a reviewer.
    assert sorted(member["employee"] for member in h["members"]) == ["Mario Collymore", "Mariocollymore"]
    [proposal] = h["review"]["aliases"]
    assert proposal["labels"] == MARIO
    assert proposal["names"] == ["Mario Collymore", "Mariocollymore"]
    assert proposal["decision"] == {"id": "proposed", "label": "Proposed"}
    assert proposal["proposed_by"] == [[829, 1072]]
    assert proposal["saved"] is False


def test_h_is_the_only_alias_the_committed_workbook_proposes(app):
    # Kerry ward / Kerryward also differ only in spacing, but never on one Date with the same claim.
    assert [(proposal["labels"], proposal["decision"]["id"]) for proposal in aliases(app)] == [(MARIO, "proposed")]


def test_f_and_h_are_separate_possible_duplicates_with_different_display_identifiers(app):
    f, h = evidence(app, 2206), evidence(app, 829)
    ranked = app.get("/api/review-priorities").json()["possible_duplicates"]

    assert member_rows(f) == {2206, 2351}
    assert member_rows(h) == {829, 1072}
    assert f["display_id"] == "Possible duplicate L224030+L224175"
    assert h["display_id"] == "Possible duplicate L225309+L225552"
    assert rule_ids(f) == ["strict_repeat", "work_period_conflict"]
    assert f["review"]["aliases"] == []
    listed = [item for item in ranked if member_rows(item) & {829, 1072, 2206, 2351}]
    assert sorted(member_rows(item) == {829, 1072} or member_rows(item) == {2206, 2351} for item in listed) == [True, True]
    # The Strict repeat compares one label, so H is no exact repeat; its Approved ticket sits beside a Pending one.
    assert h["exact_repeat_not_flagged"] is False
    assert h["tier"]["rank"] == 2


def test_the_pair_explanation_gives_the_name_space_verdict_for_h(app):
    h = pair(app, 1072, 829)

    assert h["linked"] is True
    assert h["same_employee_and_date"] is True
    assert h["employee_relation"] == "spacing_differs"
    assert [rule["rule_id"] for rule in h["rules"]] == [
        "strict_repeat", "time_text_variant", "name_space_variant", "work_period_conflict", "ambiguous_period_comparison",
        "flagged_duplicate_counterpart", "repeated_component",
    ]
    assert [rule["matched"] for rule in h["rules"]] == [False, False, True, False, False, False, False]
    assert "Employee differs" in verdict(h, "strict_repeat")["reason"]
    assert "no confirmed Alias" in verdict(h, "work_period_conflict")["reason"]


def test_two_tickets_sharing_an_email_under_different_names_are_not_proposed_as_an_alias(app):
    # Peter Holder (row 171) and Renaldo Springer (row 173), 4 October: same email, job, time and amounts.
    shared = pair(app, 171, 173)

    assert shared["same_employee_and_date"] is False
    assert shared["linked"] is False
    assert verdict(shared, "name_space_variant")["matched"] is False
    assert {tuple(proposal["labels"]) for proposal in aliases(app)} == {tuple(MARIO)}


def test_a_shared_email_never_proposes_an_alias_in_a_synthetic_workbook(tmp_path):
    workbook = write_workbook(tmp_path / "email.xlsx", [
        ticket(1, Employee="Ann Smith", Email_Address="shared@example.com"),
        ticket(2, Employee="Bea Jones", Email_Address="shared@example.com"),
    ])

    with running(workbook, tmp_path) as booted:
        fingerprint = fingerprint_of(booted)
        assert aliases(booted, fingerprint) == []
        assert booted.get(f"/api/snapshots/{fingerprint}/tickets/2/possible-duplicate").status_code == 404
        assert verdict(pair(booted, 2, 3, fingerprint), "name_space_variant")["matched"] is False


def test_the_name_space_variant_needs_the_whole_claim_and_ignores_case_and_every_space(tmp_path):
    workbook = write_workbook(tmp_path / "names.xlsx", [
        # Spaces anywhere and case: a variant.
        ticket(1, Employee="Ann Marie Smith"),
        ticket(2, Employee="annmarie  SMITH "),
        # The same spelling apart from spacing, but Overtime differs: no variant.
        ticket(3, Employee="Bob Jones", Overtime=1),
        ticket(4, Employee="BobJones"),
        # Punctuation is not spacing.
        ticket(5, Employee="St Clair Scott"),
        ticket(6, Employee="St.Clair Scott"),
    ])

    with running(workbook, tmp_path) as booted:
        fingerprint = fingerprint_of(booted)
        found = {tuple(proposal["labels"]): proposal["proposed_by"] for proposal in aliases(booted, fingerprint)}
        assert found == {("ann marie smith", "annmarie smith"): [[2, 3]]}
        assert "Overtime differs" in verdict(pair(booted, 4, 5, fingerprint), "name_space_variant")["reason"]
        assert pair(booted, 6, 7, fingerprint)["same_employee_and_date"] is False


@pytest.fixture(scope="module")
def reviewed(tmp_path_factory):
    """The committed workbook with its own data directory, so Alias decisions never leak into other modules."""
    with running(WORKBOOK, tmp_path_factory.mktemp("alias-data")) as booted:
        yield booted


def test_confirming_and_rejecting_h_records_each_decision_with_its_history(reviewed):
    before = label_count(reviewed)

    confirmed = decided(
        reviewed, ["Mario Collymore", "Mariocollymore"], "confirmed",
        reviewer="Alex Reviewer", rationale="Same email and the same claim; Oliver confirmed one person",
    )

    assert confirmed["changed"] is True
    assert confirmed["labels"] == MARIO
    assert confirmed["decision"] == {"id": "confirmed", "label": "Confirmed"}
    assert confirmed["reviewer"] == "Alex Reviewer"
    [entry] = confirmed["history"]
    assert entry["kind"] == "alias"
    assert entry["employee_labels"] == MARIO
    assert entry["excel_rows"] == [829, 1072]
    assert entry["ticket_numbers"] == ["L225552", "L225309"]
    assert entry["reviewer"] == "Alex Reviewer"
    assert dt.datetime.fromisoformat(entry["recorded_at"]).tzinfo is not None
    assert entry["previous"] is None
    assert entry["new"] == {"labels": MARIO, "decision": {"id": "confirmed", "label": "Confirmed"}}
    assert entry["rationale"] == "Same email and the same claim; Oliver confirmed one person"
    # The Alias widens the Work-period conflict on the next rule run: H's identical times now overlap, read as
    # part of the same claim. The Strict repeat still compares one label, and the labels are still counted apart.
    assert confirmed["rules_ran"] is True
    assert [(c["rule_id"], c["excel_rows"]) for c in confirmed["rerun"]["added"]] == [("work_period_conflict", [829, 1072])]
    assert confirmed["rerun"]["removed"] == []
    h = evidence(reviewed, 829)
    assert rule_ids(h) == ["name_space_variant", "work_period_conflict"]
    conflict = next(c for c in h["candidates"] if c["rule_id"] == "work_period_conflict")
    assert conflict["pattern"] == "Same claim looks different as text"
    assert "confirmed Alias" in conflict["reason"]
    assert h["review"]["aliases"][0]["decision"]["id"] == "confirmed"
    assert [item["kind"] for item in h["review"]["history"]] == ["alias"]
    assert label_count(reviewed) == before
    assert pair(reviewed, 829, 1072)["employee_relation"] == "confirmed_alias"

    rejected = decided(reviewed, MARIO, "rejected", reviewer="Sam Lead", rationale="Payroll lists two people")

    assert rejected["changed"] is True
    assert [(c["rule_id"], c["excel_rows"]) for c in rejected["rerun"]["removed"]] == [("work_period_conflict", [829, 1072])]
    assert rejected["rerun"]["added"] == []
    latest, first = rejected["history"]
    assert (latest["previous"]["decision"]["id"], latest["new"]["decision"]["id"]) == ("confirmed", "rejected")
    assert (latest["reviewer"], latest["rationale"]) == ("Sam Lead", "Payroll lists two people")
    assert first["new"]["decision"]["id"] == "confirmed"
    # The proposal itself stays a Candidate whatever is decided.
    assert rule_ids(evidence(reviewed, 829)) == ["name_space_variant"]
    assert label_count(reviewed) == before
    summary = reviewed.get(f"/api/snapshots/{HANDOFF_WORKBOOK_SHA256}/review").json()
    assert [(alias["labels"], alias["decision"]["id"]) for alias in summary["aliases"]] == [(MARIO, "rejected")]
    assert [entry["kind"] for entry in summary["history"]] == ["alias", "alias"]


def test_an_alias_decision_needs_a_proposal_a_reason_and_a_known_decision(reviewed):
    peter_renaldo = decide(reviewed, ["Peter Holder", "Renaldo Springer"], "confirmed")
    assert peter_renaldo.status_code == 404
    assert peter_renaldo.json()["detail"]["code"] == "no_alias_proposal"
    assert decide(reviewed, ["mario collymore", "Mario  Collymore"], "confirmed").json()["detail"]["code"] == "two_labels_required"
    assert decide(reviewed, MARIO, "merged").json()["detail"]["code"] == "unknown_decision"
    assert decide(reviewed, MARIO, "confirmed", rationale="").json()["detail"]["code"] == "rationale_required"
    assert decide(reviewed, MARIO, "confirmed", reviewer=" ").json()["detail"]["code"] == "missing_value"
    assert decide(reviewed, MARIO, "confirmed", rationale="maybe fraud").json()["detail"]["code"] == "banned_phrase"
    assert reviewed.client.put(
        f"/api/snapshots/{HANDOFF_WORKBOOK_SHA256}/aliases",
        json={"labels": MARIO, "decision": "confirmed", "reviewer": "X", "rationale": "Y"},
        headers={"Origin": "https://example.com"},
    ).status_code == 403


def test_saving_the_decision_already_saved_changes_nothing_and_runs_no_rules(tmp_path):
    workbook = write_workbook(tmp_path / "same.xlsx", [ticket(1, Employee="Ann Smith"), ticket(2, Employee="AnnSmith")])

    with running(workbook, tmp_path) as booted:
        fingerprint = fingerprint_of(booted)
        decided(booted, ["Ann Smith", "AnnSmith"], "rejected", fingerprint)
        again = decided(booted, ["annsmith", "ann smith"], "rejected", fingerprint, rationale="")

        assert again["changed"] is False
        assert again["rules_ran"] is False
        assert len(again["history"]) == 1


def test_after_confirming_an_alias_a_rerun_finds_a_work_period_conflict_under_the_two_labels(tmp_path):
    # 28 September proposes the Alias; on 29 September the two labels claim overlapping work on different jobs.
    other_day = dt.datetime(2026, 9, 29)
    workbook = write_workbook(tmp_path / "alias.xlsx", [
        ticket(1, Employee="Ann Smith"),
        ticket(2, Employee="AnnSmith"),
        ticket(3, Employee="Ann Smith", Date=other_day, Time="7:30am-11:30am", Regular_Hours=4),
        ticket(4, Employee="AnnSmith", Date=other_day, Job_Number=20105, Time="10:30am-2:30pm", Regular_Hours=4),
        # Bea Jones overlaps on that day too, under a different name: never compared.
        ticket(5, Employee="Bea Jones", Date=other_day, Time="7:30am-11:30am", Regular_Hours=4),
    ])
    labels = ["ann smith", "annsmith"]
    data_dir = tmp_path / "data"

    with running(workbook, data_dir) as booted:
        fingerprint = fingerprint_of(booted)
        before = pair(booted, 4, 5, fingerprint)
        assert before["linked"] is False
        assert "no confirmed Alias" in verdict(before, "work_period_conflict")["reason"]
        assert booted.get(f"/api/snapshots/{fingerprint}/tickets/5/possible-duplicate").status_code == 404
        assert label_count(booted) == 3
        # An outcome saved on the proposing pair survives every rerun.
        saved = booted.client.put(
            f"/api/snapshots/{fingerprint}/pairs/2/3/outcome",
            json={"outcome": "needs_follow_up", "note": "Ask about the name", "reference": "", "reviewer": "Sam", "rationale": ""},
        )
        assert saved.status_code == 200, saved.text

        confirmed = decided(booted, labels, "confirmed", fingerprint)

        assert [(c["rule_id"], c["excel_rows"]) for c in confirmed["rerun"]["added"]] == [
            ("work_period_conflict", [2, 3]),
            ("work_period_conflict", [4, 5]),
        ]
        widened = evidence(booted, 5, fingerprint)
        assert member_rows(widened) == {4, 5}
        [conflict] = widened["candidates"]
        assert conflict["rule_id"] == "work_period_conflict"
        assert conflict["pattern"] == "Possible correction or resubmission"
        assert "on different jobs" in conflict["reason"] and "10:30-11:30" in conflict["reason"]
        # The Alias widens only the rules that accept one, and joins only its own two labels.
        assert widened["review"]["aliases"][0]["decision"]["id"] == "confirmed"
        assert pair(booted, 4, 6, fingerprint)["linked"] is False
        assert pair(booted, 5, 6, fingerprint)["same_employee_and_date"] is False
        assert label_count(booted) == 3
        proposing = evidence(booted, 2, fingerprint)
        assert proposing["review"]["pairs"][0]["outcome"]["id"] == "needs_follow_up"

    # On the next launch the rules run under the stored Alias again.
    with running(workbook, data_dir) as booted:
        assert evidence(booted, 5, fingerprint)["candidates"][0]["rule_id"] == "work_period_conflict"
        rejected = decided(booted, labels, "rejected", fingerprint)

        assert [(c["rule_id"], c["excel_rows"]) for c in rejected["rerun"]["removed"]] == [
            ("work_period_conflict", [2, 3]),
            ("work_period_conflict", [4, 5]),
        ]
        assert booted.get(f"/api/snapshots/{fingerprint}/tickets/5/possible-duplicate").status_code == 404
        assert pair(booted, 4, 5, fingerprint)["linked"] is False
        assert evidence(booted, 2, fingerprint)["review"]["pairs"][0]["outcome"]["id"] == "needs_follow_up"
        assert [entry["new"]["decision"]["id"] for entry in aliases(booted, fingerprint)[0]["history"]] == [
            "rejected", "confirmed",
        ]


# The review file as ticket #8 wrote it (schema version 1), before Alias decisions existed.
REVIEW_FILE_V1 = """
CREATE TABLE review_store (schema_version INTEGER NOT NULL);
INSERT INTO review_store VALUES (1);
CREATE SEQUENCE review_history_entry START 1;
CREATE TABLE review_outcomes (
    snapshot_fingerprint VARCHAR NOT NULL, first_row INTEGER NOT NULL, second_row INTEGER NOT NULL,
    first_ticket_number VARCHAR, second_ticket_number VARCHAR, outcome VARCHAR NOT NULL, note VARCHAR NOT NULL,
    reference VARCHAR NOT NULL, reviewer VARCHAR NOT NULL, recorded_at VARCHAR NOT NULL,
    PRIMARY KEY (snapshot_fingerprint, first_row, second_row), CHECK (first_row < second_row)
);
CREATE TABLE replacement_links (
    snapshot_fingerprint VARCHAR NOT NULL, replaced_row INTEGER NOT NULL, retained_row INTEGER NOT NULL,
    replaced_ticket_number VARCHAR, retained_ticket_number VARCHAR, reviewer VARCHAR NOT NULL,
    recorded_at VARCHAR NOT NULL, rationale VARCHAR NOT NULL,
    PRIMARY KEY (snapshot_fingerprint, replaced_row, retained_row), CHECK (replaced_row <> retained_row)
);
CREATE TABLE review_history (
    entry BIGINT PRIMARY KEY DEFAULT nextval('review_history_entry'), snapshot_fingerprint VARCHAR NOT NULL,
    kind VARCHAR NOT NULL, excel_rows INTEGER[] NOT NULL, ticket_numbers VARCHAR[] NOT NULL,
    reviewer VARCHAR NOT NULL, recorded_at VARCHAR NOT NULL, previous_value JSON, new_value JSON,
    rationale VARCHAR NOT NULL
);
"""


def test_a_review_file_from_before_aliases_keeps_its_outcomes_and_takes_alias_decisions(tmp_path):
    workbook = write_workbook(tmp_path / "old.xlsx", [ticket(1, Employee="Ann Smith"), ticket(2, Employee="AnnSmith")])
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    with running(workbook, tmp_path / "probe") as booted:
        fingerprint = fingerprint_of(booted)
    with duckdb.connect(str(data_dir / "review.duckdb")) as connection:
        connection.execute(REVIEW_FILE_V1)
        connection.execute(
            "INSERT INTO review_outcomes VALUES (?, 2, 3, 'L000001', 'L000002', 'needs_follow_up', 'Old note', '',"
            " 'Sam', '2026-10-14T09:00:00Z')",
            [fingerprint],
        )

    with running(workbook, data_dir) as booted:
        outcome = booted.get(f"/api/snapshots/{fingerprint}/pairs/2/3/outcome").json()
        assert (outcome["outcome"]["id"], outcome["note"]) == ("needs_follow_up", "Old note")
        assert decided(booted, ["ann smith", "annsmith"], "confirmed", fingerprint)["changed"] is True


def test_only_the_rules_worded_or_confirmed_alias_accept_one(app):
    rules = {rule["id"]: rule for rule in app.get("/api/review-priorities").json()["rules"]}

    # PRD section 5: the Work-period conflict, and from ticket #11 the Flagged-duplicate counterpart and Repeated component.
    assert [rule_id for rule_id, rule in rules.items() if rule["accepts_alias"]] == [
        "work_period_conflict", "flagged_duplicate_counterpart", "repeated_component",
    ]
    assert rules["name_space_variant"]["label"] == "Name-space variant"
    assert rules["name_space_variant"]["evidence_strength"] == "moderate"
    assert rules["name_space_variant"]["pattern"] == "Same claim looks different as text"
