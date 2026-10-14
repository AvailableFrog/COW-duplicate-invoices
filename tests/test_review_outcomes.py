"""Ticket #8: local Review Outcomes on Ticket pairs, kept/replaced links and their history.

Outcomes attach to the order-independent pair of Tickets behind a Candidate
and are shown by the possible duplicate holding them, never keyed by it
(ADR 0004). They live in a local DuckDB file in the data directory, apart from
the Snapshot, keyed to the Snapshot fingerprint (ADR 0002).
"""

import datetime as dt
import hashlib
import subprocess

import duckdb
import pytest

from conftest import HANDOFF_WORKBOOK_SHA256, REPO_ROOT, WORKBOOK, launch_command, running
from synthetic import ticket, write_workbook

OUTCOMES = {
    "not_reviewed": "Not reviewed",
    "confirmed_duplicate": "Confirmed duplicate",
    "not_a_duplicate": "Not a duplicate",
    "replacement_ticket": "Replacement ticket",
    "needs_follow_up": "Needs follow-up",
}


@pytest.fixture(scope="module")
def reviewed(tmp_path_factory):
    """The committed workbook with its own data directory, so saved outcomes never leak into other modules."""
    with running(WORKBOOK, tmp_path_factory.mktemp("review-data")) as booted:
        yield booted


def pair_path(first: int, second: int, fingerprint: str = HANDOFF_WORKBOOK_SHA256) -> str:
    return f"/api/snapshots/{fingerprint}/pairs/{first}/{second}/outcome"


def save(app, first: int, second: int, fingerprint: str = HANDOFF_WORKBOOK_SHA256, **body) -> dict:
    payload = {"reviewer": "Test reviewer", "note": "", "reference": "", "rationale": "", **body}
    response = app.client.put(pair_path(first, second, fingerprint), json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def evidence(app, excel_row: int, fingerprint: str = HANDOFF_WORKBOOK_SHA256) -> dict:
    response = app.get(f"/api/snapshots/{fingerprint}/tickets/{excel_row}/possible-duplicate")
    assert response.status_code == 200, response.text
    return response.json()


def test_an_unreviewed_pair_reads_not_reviewed_with_no_history(reviewed):
    # Rows 425/1191, the Approved/Pending pair: nothing is ever saved on it in this module.
    response = reviewed.get(pair_path(1191, 425))

    assert response.status_code == 200
    body = response.json()
    assert body["excel_rows"] == [425, 1191]
    assert body["outcome"] == {"id": "not_reviewed", "label": "Not reviewed"}
    assert body["saved"] is False
    assert body["history"] == []


def test_an_outcome_saved_on_the_peter_holder_pair_shows_against_that_pair_in_the_drawer(reviewed):
    save(
        reviewed, 855, 620,
        outcome="confirmed_duplicate", note="Same claim twice", reference="Email from Oliver, 9 Oct", rationale="",
    )

    review = evidence(reviewed, 620)["review"]

    assert [
        (pair["excel_rows"], pair["ticket_numbers"], pair["outcome"]["label"], pair["note"], pair["reference"], pair["reviewer"])
        for pair in review["pairs"]
    ] == [([620, 855], ["L225761", "L225526"], "Confirmed duplicate", "Same claim twice", "Email from Oliver, 9 Oct", "Test reviewer")]
    assert [(o["id"], o["label"]) for o in review["outcome_values"]] == list(OUTCOMES.items())


def test_setting_an_outcome_on_the_pair_in_either_order_resolves_to_the_same_record(reviewed):
    # E, rows 1309/1656.
    save(reviewed, 1656, 1309, outcome="needs_follow_up", note="Ask Oliver")

    forward = reviewed.get(pair_path(1309, 1656)).json()
    backward = reviewed.get(pair_path(1656, 1309)).json()
    revised = save(reviewed, 1309, 1656, outcome="confirmed_duplicate", note="Ask Oliver", rationale="Oliver agreed")

    assert forward == backward
    assert forward["excel_rows"] == [1309, 1656]
    assert forward["outcome"]["label"] == "Needs follow-up"
    assert revised["excel_rows"] == [1309, 1656]
    assert [entry["new"]["outcome"]["label"] for entry in revised["history"]] == ["Confirmed duplicate", "Needs follow-up"]
    saved_pairs = [o["excel_rows"] for o in reviewed.get(f"/api/snapshots/{HANDOFF_WORKBOOK_SHA256}/review").json()["outcomes"]]
    assert saved_pairs.count([1309, 1656]) == 1


def test_revising_an_outcome_appends_a_history_row_with_reviewer_time_previous_new_and_rationale(reviewed):
    # F, rows 2206/2351.
    first = save(reviewed, 2206, 2351, outcome="needs_follow_up", note="Check with payroll", reviewer="Alex")
    second = save(
        reviewed, 2351, 2206,
        outcome="not_a_duplicate", note="Separate shifts", reference="Site diary p.4", reviewer="Sam",
        rationale="Site diary shows two shifts",
    )

    assert len(first["history"]) == 1
    history = second["history"]
    assert len(history) == 2
    newest = history[0]
    assert newest["reviewer"] == "Sam"
    assert newest["rationale"] == "Site diary shows two shifts"
    assert newest["previous"] == {
        "outcome": {"id": "needs_follow_up", "label": "Needs follow-up"}, "note": "Check with payroll", "reference": "",
    }
    assert newest["new"] == {
        "outcome": {"id": "not_a_duplicate", "label": "Not a duplicate"}, "note": "Separate shifts", "reference": "Site diary p.4",
    }
    assert history[1]["previous"] is None and history[1]["reviewer"] == "Alex"
    recorded = [dt.datetime.fromisoformat(entry["recorded_at"]) for entry in history]
    assert all(time.tzinfo is not None for time in recorded)
    assert recorded[0] >= recorded[1]
    # The drawer reads the same history.
    assert evidence(reviewed, 2206)["review"]["history"] == history


def test_each_of_the_five_outcomes_can_be_set_and_a_revision_needs_a_rationale(reviewed):
    # Rows 84/88, the Pending/Pending pair.
    for index, (outcome, label) in enumerate(OUTCOMES.items()):
        saved = save(reviewed, 84, 88, outcome=outcome, note=f"note {index}", reference=f"ref {index}", rationale=f"step {index}")
        assert saved["outcome"] == {"id": outcome, "label": label}
        assert evidence(reviewed, 88)["review"]["pairs"][0]["outcome"]["label"] == label

    unexplained = reviewed.client.put(
        pair_path(84, 88), json={"outcome": "confirmed_duplicate", "reviewer": "Test reviewer", "rationale": "  "},
    )
    unchanged = save(reviewed, 84, 88, outcome="needs_follow_up", note="note 4", reference="ref 4")

    assert unexplained.status_code == 422
    assert unexplained.json()["detail"]["code"] == "rationale_required"
    assert unchanged["changed"] is False
    assert len(unchanged["history"]) == 5


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"outcome": "confirmed", "reviewer": "Alex"}, "unknown_outcome"),
        ({"outcome": "confirmed_duplicate", "reviewer": "   "}, "missing_value"),
        ({"outcome": "confirmed_duplicate", "reviewer": "Alex", "note": "Looks like he was Paid Twice"}, "banned_phrase"),
        ({"outcome": "confirmed_duplicate", "reviewer": "Alex", "reference": "x" * 501}, "too_long"),
    ],
)
def test_an_invalid_outcome_is_refused_and_nothing_is_saved(reviewed, body, code):
    # Rows 425/1191, the Approved/Pending pair, never saved in this module.
    response = reviewed.client.put(pair_path(425, 1191), json=body)

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == code
    assert reviewed.get(pair_path(425, 1191)).json()["saved"] is False


def test_an_outcome_only_attaches_to_a_pair_a_candidate_links(reviewed):
    unlinked = reviewed.client.put(pair_path(620, 974), json={"outcome": "confirmed_duplicate", "reviewer": "Alex"})
    same = reviewed.get(pair_path(620, 620))
    unknown = reviewed.get(pair_path(620, 855, "0" * 64))

    assert unlinked.status_code == 404
    assert unlinked.json()["detail"]["code"] == "no_candidate"
    assert same.status_code == 404
    assert unknown.status_code == 404


def test_saving_from_another_sites_page_is_refused(reviewed):
    body = {"outcome": "confirmed_duplicate", "reviewer": "Alex"}

    refused = reviewed.client.put(pair_path(425, 1191), json=body, headers={"Origin": "https://attacker.example"})
    link = reviewed.client.put(
        f"/api/snapshots/{HANDOFF_WORKBOOK_SHA256}/replacement-links/425/1191",
        json={"reviewer": "Alex"}, headers={"Origin": "https://attacker.example"},
    )

    assert refused.status_code == 403
    assert link.status_code == 403
    assert reviewed.get(pair_path(425, 1191)).json()["saved"] is False


def test_the_ranked_list_carries_each_pairs_outcome_without_changing_its_order(reviewed):
    before = reviewed.get("/api/review-priorities").json()["possible_duplicates"]
    save(reviewed, 974, 1868, outcome="confirmed_duplicate", note="D")
    after = reviewed.get("/api/review-priorities").json()["possible_duplicates"]

    d = next(item for item in after if {m["excel_row"] for m in item["members"]} == {974, 1868})
    assert [c["outcome"] for c in d["candidates"]] == [{"id": "confirmed_duplicate", "label": "Confirmed duplicate"}]
    assert [(item["display_id"], item["rank"], item["tier"]) for item in after] == [
        (item["display_id"], item["rank"], item["tier"]) for item in before
    ]


def three_repeats(tmp_path):
    """One possible duplicate of three Tickets (rows 2, 3, 4), every pair a Strict repeat Candidate."""
    return write_workbook(tmp_path / "three.xlsx", [ticket(number, Employee="Ann Smith") for number in (1, 2, 3)])


def link_path(fingerprint: str, replaced: int, retained: int) -> str:
    return f"/api/snapshots/{fingerprint}/replacement-links/{replaced}/{retained}"


def test_a_replaced_ticket_can_be_linked_to_two_kept_tickets_and_both_links_are_shown(tmp_path):
    with running(three_repeats(tmp_path), tmp_path / "data") as booted:
        fingerprint = booted.get("/api/snapshot").json()["snapshot_fingerprint"]
        first = booted.client.put(link_path(fingerprint, 4, 2), json={"reviewer": "Alex", "rationale": "Resubmitted"})
        second = booted.client.put(link_path(fingerprint, 4, 3), json={"reviewer": "Alex", "rationale": "Covers both"})
        again = booted.client.put(link_path(fingerprint, 4, 3), json={"reviewer": "Alex"})
        review = evidence(booted, 2, fingerprint)["review"]
        summary = booted.get(f"/api/snapshots/{fingerprint}/review").json()

    assert first.status_code == second.status_code == again.status_code == 200
    assert again.json()["changed"] is False
    expected = [
        (4, "L000003", 2, "L000001", "Alex", "Resubmitted"),
        (4, "L000003", 3, "L000002", "Alex", "Covers both"),
    ]
    shown = [
        (l["replaced_row"], l["replaced_ticket_number"], l["retained_row"], l["retained_ticket_number"], l["reviewer"], l["rationale"])
        for l in review["links"]
    ]
    assert shown == expected
    assert [(l["replaced_row"], l["retained_row"]) for l in summary["links"]] == [(4, 2), (4, 3)]
    assert summary["replaced_tickets"] == [4]
    # Each link made is a history row; a repeated link adds none.
    assert [(e["kind"], e["excel_rows"], e["previous"], e["new"]["retained_row"]) for e in review["history"]] == [
        ("link", [4, 3], None, 3),
        ("link", [4, 2], None, 2),
    ]
    # Three Tickets, three Candidate pairs, each shown with its own outcome.
    assert [pair["excel_rows"] for pair in review["pairs"]] == [[2, 3], [2, 4], [3, 4]]


def test_a_link_can_be_removed_with_a_history_row_and_contradictory_or_unrelated_links_are_refused(tmp_path):
    with running(three_repeats(tmp_path), tmp_path / "data") as booted:
        fingerprint = booted.get("/api/snapshot").json()["snapshot_fingerprint"]
        booted.client.put(link_path(fingerprint, 4, 2), json={"reviewer": "Alex"})
        reverse = booted.client.put(link_path(fingerprint, 2, 4), json={"reviewer": "Alex"})
        itself = booted.client.put(link_path(fingerprint, 4, 4), json={"reviewer": "Alex"})
        outside = booted.client.put(link_path(fingerprint, 4, 9), json={"reviewer": "Alex"})
        removed = booted.client.request("DELETE", link_path(fingerprint, 4, 2), json={"reviewer": "Sam", "rationale": "Wrong way round"})
        missing = booted.client.request("DELETE", link_path(fingerprint, 4, 2), json={"reviewer": "Sam"})
        review = evidence(booted, 2, fingerprint)["review"]

    assert reverse.status_code == 409
    assert itself.status_code == 422
    assert outside.status_code == 404
    assert removed.status_code == 200
    assert missing.status_code == 404
    assert review["links"] == []
    newest = review["history"][0]
    assert (newest["kind"], newest["reviewer"], newest["rationale"], newest["new"]) == ("link", "Sam", "Wrong way round", None)
    assert (newest["previous"]["replaced_row"], newest["previous"]["retained_row"]) == (4, 2)


def test_tickets_in_different_possible_duplicates_cannot_be_linked(reviewed):
    response = reviewed.client.put(link_path(HANDOFF_WORKBOOK_SHA256, 620, 974), json={"reviewer": "Alex"})

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "not_in_one_possible_duplicate"


def sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_outcomes_links_and_history_survive_a_restart_and_a_different_snapshot_starts_with_none(tmp_path):
    data_dir = tmp_path / "data"
    workbook_hash = sha256(WORKBOOK)
    with running(WORKBOOK, data_dir) as booted:
        save(booted, 620, 855, outcome="needs_follow_up", note="Ask Oliver")
        save(booted, 620, 855, outcome="replacement_ticket", note="Ask Oliver", rationale="Oliver confirmed")
        booted.client.put(link_path(HANDOFF_WORKBOOK_SHA256, 620, 855), json={"reviewer": "Alex"})
        before = booted.get(f"/api/snapshots/{HANDOFF_WORKBOOK_SHA256}/review").json()

    with running(WORKBOOK, data_dir) as booted:
        after = booted.get(f"/api/snapshots/{HANDOFF_WORKBOOK_SHA256}/review").json()
        drawer = evidence(booted, 855)["review"]

    other = write_workbook(tmp_path / "other.xlsx", [ticket(1, Employee="Ann Smith"), ticket(2, Employee="Ann Smith")])
    with running(other, data_dir) as booted:
        fingerprint = booted.get("/api/snapshot").json()["snapshot_fingerprint"]
        fresh = booted.get(f"/api/snapshots/{fingerprint}/review").json()
        fresh_pair = booted.get(pair_path(2, 3, fingerprint)).json()

    for key in ("outcomes", "links", "history", "replaced_tickets"):
        assert after[key] == before[key]
    assert [o["outcome"]["label"] for o in after["outcomes"]] == ["Replacement ticket"]
    assert len(after["history"]) == 3
    assert drawer["pairs"][0]["outcome"]["label"] == "Replacement ticket"
    assert fingerprint != HANDOFF_WORKBOOK_SHA256
    assert (fresh["outcomes"], fresh["links"], fresh["history"], fresh["replaced_tickets"]) == ([], [], [], [])
    assert (fresh_pair["outcome"]["label"], fresh_pair["history"]) == ("Not reviewed", [])
    assert sha256(WORKBOOK) == workbook_hash == HANDOFF_WORKBOOK_SHA256


def test_saving_never_touches_the_workbook_and_the_review_tables_are_in_their_own_file(tmp_path):
    workbook = write_workbook(tmp_path / "export.xlsx", [ticket(1, Employee="Ann Smith"), ticket(2, Employee="Ann Smith")])
    data_dir = tmp_path / "data"
    workbook_hash = sha256(workbook)
    modified = workbook.stat().st_mtime_ns
    with running(workbook, data_dir) as booted:
        fingerprint = booted.get("/api/snapshot").json()["snapshot_fingerprint"]
        save(booted, 2, 3, fingerprint, outcome="confirmed_duplicate", note="Same claim")
        booted.client.put(link_path(fingerprint, 3, 2), json={"reviewer": "Alex"})
        store = booted.get(f"/api/snapshots/{fingerprint}/review").json()["store"]
        header = booted.get("/api/snapshot").json()["snapshot"]

    assert (sha256(workbook), workbook.stat().st_mtime_ns) == (workbook_hash, modified)
    assert header["fingerprint"] == fingerprint == workbook_hash
    review_file = data_dir / store["file"]
    assert store["path"] == str(review_file.resolve())
    assert review_file.is_file() and review_file.parent != workbook.parent
    # The Snapshot's source tables are rebuilt in memory on each launch; none of them is in the review file.
    with duckdb.connect(str(review_file), read_only=True) as connection:
        tables = {row[0] for row in connection.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    assert tables.isdisjoint({"snapshots", "tickets", "cells", "ticket_values", "import_issues", "candidates"})


def numbers(app) -> dict:
    """Every number the application shows today: each registry metric, the tiles and the ranked list's order."""
    metric_ids = [metric["id"] for metric in app.get("/api/metrics").json()["metrics"]]
    responses = {metric_id: app.get(f"/api/metrics/{metric_id}", params={"rows": "true"}) for metric_id in metric_ids}
    assert {response.status_code for response in responses.values()} == {200}
    metrics = {metric_id: response.json() for metric_id, response in responses.items()}
    tiles = app.get("/api/overview/tiles").json()["tiles"]
    ranked = [
        (item["rank"], item["display_id"], item["tier"]["rank"])
        for item in app.get("/api/review-priorities").json()["possible_duplicates"]
    ]
    return {"metrics": metrics, "tiles": tiles, "ranked": ranked}


def test_a_needs_follow_up_outcome_with_a_note_contributes_nothing_to_any_figure(tmp_path):
    with running(WORKBOOK, tmp_path / "data") as booted:
        before = numbers(booted)
        save(booted, 620, 855, outcome="needs_follow_up", note="Ask Oliver whether one was excluded elsewhere")
        after = numbers(booted)
        summary = booted.get(f"/api/snapshots/{HANDOFF_WORKBOOK_SHA256}/review").json()

    assert after == before
    # Only an explicit link names a Ticket an adjusted figure may leave out, and there is none.
    assert summary["links"] == []
    assert summary["replaced_tickets"] == []


def test_a_second_copy_on_the_same_data_directory_is_refused_with_a_message(tmp_path):
    with running(WORKBOOK, tmp_path / "data"):
        second = subprocess.run(
            launch_command(WORKBOOK, "--port", "0", "--data-dir", str(tmp_path / "data")),
            capture_output=True, text=True, timeout=60, cwd=REPO_ROOT,
        )

    assert second.returncode == 2
    assert "review store" in second.stderr
    assert "Listening on" not in second.stdout
