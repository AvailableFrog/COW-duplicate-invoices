"""Ticket #40: carrying review decisions forward to a new Snapshot.

After a changed export is imported, the outcomes, kept/replaced links and
Alias decisions saved on the earlier Snapshot are proposed, matched by ticket
number (or, for an Alias, by its two labels), never applied silently. An
unchanged proposal is carried in one step; a changed one shows what changed
and needs explicit revalidation. A carried decision keeps its reviewer, time
and rationale, beside who carried it forward and when; the earlier
Snapshot's decisions stay as they were.
"""

import duckdb

from conftest import running
from synthetic import ticket, write_workbook


def repeats(*numbers: int, changes: dict[int, dict] | None = None) -> list[dict]:
    """Tickets under one employee with every claim field equal: each pair is a strict repeat."""
    return [ticket(number, Employee="Ann Smith", **(changes or {}).get(number, {})) for number in numbers]


def fingerprint(app) -> str:
    return app.get("/api/snapshot").json()["snapshot_fingerprint"]


def save_outcome(app, fp: str, first: int, second: int, **body) -> None:
    response = app.client.put(
        f"/api/snapshots/{fp}/pairs/{first}/{second}/outcome",
        json={"reviewer": "Sam", "rationale": "", "note": "", "reference": "", **body},
    )
    assert response.status_code == 200, response.text


def link(app, fp: str, replaced: int, retained: int, **body) -> None:
    response = app.client.put(
        f"/api/snapshots/{fp}/replacement-links/{replaced}/{retained}", json={"reviewer": "Sam", **body},
    )
    assert response.status_code == 200, response.text


def proposals(app, fp: str) -> dict:
    response = app.get(f"/api/snapshots/{fp}/carry-forward")
    assert response.status_code == 200, response.text
    return response.json()


def answer(app, fp: str, proposal: dict, action: str = "carry", **body):
    return app.client.post(
        f"/api/snapshots/{fp}/carry-forward", json={"id": proposal["id"], "action": action, "reviewer": "Alex", **body},
    )


def by_subject(listed: dict) -> dict:
    return {(item["kind"], tuple(item["subject"])): item for item in listed["proposals"]}


def reimport(app, path, tickets) -> str:
    write_workbook(path, tickets)
    response = app.client.post("/api/snapshot/reimport")
    assert response.status_code == 200, response.text
    assert response.json()["imported"] is True
    return response.json()["snapshot_fingerprint"]


def test_after_a_reimport_earlier_decisions_are_proposed_matched_by_ticket_number_and_nothing_is_applied(tmp_path):
    path = write_workbook(tmp_path / "export.xlsx", repeats(1, 2, 3))
    with running(path, tmp_path / "data") as booted:
        old = fingerprint(booted)
        save_outcome(booted, old, 2, 3, outcome="confirmed_duplicate", note="Same claim twice")
        link(booted, old, 3, 2, rationale="Kept the earlier one")
        # The new export has another ticket above them, so every Excel row moves down by one.
        new = reimport(booted, path, [ticket(9, Employee="Bo Lee"), *repeats(1, 2, 3)])
        listed = proposals(booted, new)
        new_review = booted.get(f"/api/snapshots/{new}/review").json()

    found = by_subject(listed)
    assert set(found) == {("outcome", ("L000001", "L000002")), ("link", ("L000002", "L000001"))}
    outcome = found[("outcome", ("L000001", "L000002"))]
    assert outcome["source"] == {"snapshot_fingerprint": old, "excel_rows": [2, 3]}
    assert outcome["target"] == {"excel_rows": [3, 4], "ticket_numbers": ["L000001", "L000002"]}
    assert (outcome["status"], outcome["needs_revalidation"], outcome["differences"]) == ("unchanged", False, [])
    assert outcome["decision"]["value"]["outcome"]["label"] == "Confirmed duplicate"
    assert outcome["decision"]["reviewer"] == "Sam"
    assert found[("link", ("L000002", "L000001"))]["target"]["excel_rows"] == [4, 3]
    # Proposals only: nothing is saved on the new Snapshot until a reviewer acts.
    assert (new_review["outcomes"], new_review["links"], new_review["history"]) == ([], [], [])


def test_an_unchanged_proposal_is_carried_in_one_step_keeping_its_reviewer_time_and_rationale(tmp_path):
    path = write_workbook(tmp_path / "export.xlsx", repeats(1, 2))
    with running(path, tmp_path / "data") as booted:
        old = fingerprint(booted)
        save_outcome(booted, old, 2, 3, outcome="needs_follow_up", note="Ask Oliver")
        save_outcome(booted, old, 2, 3, outcome="confirmed_duplicate", note="Ask Oliver", rationale="Oliver agreed")
        before = booted.get(f"/api/snapshots/{old}/review").json()
        new = reimport(booted, path, [ticket(9, Employee="Bo Lee"), *repeats(1, 2)])
        [proposal] = proposals(booted, new)["proposals"]
        carried = answer(booted, new, proposal)
        new_review = booted.get(f"/api/snapshots/{new}/review").json()
        after = booted.get(f"/api/snapshots/{old}/review").json()

    assert carried.status_code == 200, carried.text
    body = carried.json()
    assert body["proposals"] == []
    [record] = body["carried"]
    assert (record["kind"], record["subject"], record["reviewer"], record["source_fingerprint"]) == (
        "outcome", ["L000001", "L000002"], "Alex", old,
    )
    [outcome] = new_review["outcomes"]
    [saved_before] = before["outcomes"]
    assert outcome["excel_rows"] == [3, 4]
    assert outcome["outcome"]["label"] == "Confirmed duplicate"
    assert (outcome["reviewer"], outcome["recorded_at"]) == (saved_before["reviewer"], saved_before["recorded_at"])
    [entry] = new_review["history"]
    assert entry["reviewer"] == "Alex"
    assert entry["new"]["carried_from"]["rationale"] == "Oliver agreed"
    assert entry["new"]["carried_from"]["reviewer"] == "Sam"
    assert "Carried forward from Snapshot" in entry["rationale"] and "Oliver agreed" in entry["rationale"]
    # The earlier Snapshot's decisions are untouched.
    assert after == before


def test_a_proposal_whose_tickets_changed_shows_what_changed_and_needs_revalidation(tmp_path):
    path = write_workbook(tmp_path / "export.xlsx", repeats(1, 2))
    with running(path, tmp_path / "data") as booted:
        old = fingerprint(booted)
        save_outcome(booted, old, 2, 3, outcome="confirmed_duplicate")
        new = reimport(booted, path, repeats(1, 2, changes={2: {"Approval_Status": "Pending", "Modified_By": "Reviewer B"}}))
        [proposal] = proposals(booted, new)["proposals"]
        refused = answer(booted, new, proposal)
        no_reason = answer(booted, new, proposal, revalidated=True)
        carried = answer(booted, new, proposal, revalidated=True, rationale="Checked: the status changed, the claim did not")
        new_review = booted.get(f"/api/snapshots/{new}/review").json()

    assert (proposal["status"], proposal["needs_revalidation"]) == ("changed", True)
    assert {(d["ticket_number"], d["field"], d["before"], d["after"]) for d in proposal["differences"]} == {
        ("L000002", "Approval Status", "Approved", "Pending"),
        ("L000002", "Modified By", "Reviewer A", "Reviewer B"),
    }
    assert refused.status_code == 422 and refused.json()["detail"]["field"] == "revalidated"
    assert no_reason.status_code == 422 and no_reason.json()["detail"]["field"] == "rationale"
    assert new_review["outcomes"][0]["outcome"]["label"] == "Confirmed duplicate"
    [record] = carried.json()["carried"]
    assert record["revalidated"] is True
    assert [d["field"] for d in record["differences"]] == ["Approval Status", "Modified By"]
    assert "after revalidating" in new_review["history"][0]["rationale"]


def test_a_declined_proposal_is_not_carried_and_not_proposed_again(tmp_path):
    path = write_workbook(tmp_path / "export.xlsx", repeats(1, 2))
    with running(path, tmp_path / "data") as booted:
        old = fingerprint(booted)
        link(booted, old, 3, 2)
        new = reimport(booted, path, repeats(1, 2, 3))
        [proposal] = proposals(booted, new)["proposals"]
        declined = answer(booted, new, proposal, action="decline", rationale="Not sure any more")
        again = answer(booted, new, proposal)
        new_review = booted.get(f"/api/snapshots/{new}/review").json()

    assert declined.status_code == 200, declined.text
    assert declined.json()["proposals"] == []
    [record] = declined.json()["declined"]
    assert (record["kind"], record["reviewer"], record["rationale"]) == ("link", "Alex", "Not sure any more")
    assert again.status_code == 404
    assert new_review["links"] == [] and new_review["replaced_tickets"] == []


def test_decisions_the_new_export_cannot_hold_can_only_be_declined(tmp_path):
    path = write_workbook(tmp_path / "export.xlsx", repeats(1, 2, 3, 4))
    with running(path, tmp_path / "data") as booted:
        old = fingerprint(booted)
        save_outcome(booted, old, 2, 3, outcome="confirmed_duplicate")
        save_outcome(booted, old, 4, 5, outcome="not_a_duplicate")
        # Ticket 2 is gone; ticket 4 now belongs to another employee, so no rule links it with ticket 3.
        new = reimport(booted, path, [*repeats(1, 3), ticket(4, Employee="Bo Lee")])
        found = by_subject(proposals(booted, new))
        missing = found[("outcome", ("L000001", "L000002"))]
        unlinked = found[("outcome", ("L000003", "L000004"))]
        refused = answer(booted, new, missing)
        declined = answer(booted, new, unlinked, action="decline")

    assert (missing["status"], missing["reason"]) == ("cannot_carry", "Ticket L000002 is not in this export.")
    assert unlinked["status"] == "cannot_carry" and "No rule links these tickets" in unlinked["reason"]
    assert refused.status_code == 409
    assert declined.status_code == 200


def test_a_carried_alias_runs_the_rules_again_on_the_new_snapshot(tmp_path):
    names = [ticket(1, Employee="Ann Smith"), ticket(2, Employee="AnnSmith")]
    path = write_workbook(tmp_path / "export.xlsx", names)
    with running(path, tmp_path / "data") as booted:
        old = fingerprint(booted)
        [alias] = booted.get(f"/api/snapshots/{old}/aliases").json()["aliases"]
        decided = booted.client.put(
            f"/api/snapshots/{old}/aliases",
            json={"labels": alias["labels"], "decision": "confirmed", "reviewer": "Sam", "rationale": "Same person"},
        )
        assert decided.status_code == 200, decided.text
        new = reimport(booted, path, [*names, ticket(3)])
        [proposal] = proposals(booted, new)["proposals"]
        carried = answer(booted, new, proposal)
        [alias_now] = booted.get(f"/api/snapshots/{new}/aliases").json()["aliases"]

    assert (proposal["kind"], proposal["subject"], proposal["status"]) == ("alias", alias["labels"], "unchanged")
    assert proposal["target"]["excel_rows"] == [2, 3]
    assert carried.status_code == 200, carried.text
    assert carried.json()["rules_ran"] is True
    assert (alias_now["decision"]["id"], alias_now["reviewer"], alias_now["rationale"]) == ("confirmed", "Sam", "Same person")


def test_after_a_relaunch_on_the_new_export_the_kept_values_are_still_compared(tmp_path):
    first = write_workbook(tmp_path / "first.xlsx", repeats(1, 2))
    data = tmp_path / "data"
    with running(first, data) as booted:
        old = fingerprint(booted)
        save_outcome(booted, old, 2, 3, outcome="confirmed_duplicate")

    second = write_workbook(tmp_path / "second.xlsx", repeats(1, 2, changes={1: {"Rate": 15.10}}))
    with running(second, data) as relaunched:
        new = fingerprint(relaunched)
        [proposal] = proposals(relaunched, new)["proposals"]

    assert old != new
    assert proposal["source"]["snapshot_fingerprint"] == old
    assert proposal["status"] == "changed"
    assert [(d["ticket_number"], d["field"], d["before"], d["after"]) for d in proposal["differences"]] == [
        ("L000001", "Rate", 14.53, 15.1),
    ]


def test_a_decision_from_before_values_were_kept_cannot_be_compared_and_needs_revalidation(tmp_path):
    first = write_workbook(tmp_path / "first.xlsx", repeats(1, 2))
    data = tmp_path / "data"
    with running(first, data) as booted:
        save_outcome(booted, fingerprint(booted), 2, 3, outcome="confirmed_duplicate")
    # As if the decision were saved before this release: its tickets' values were never kept.
    with duckdb.connect(str(data / "review.duckdb")) as connection:
        connection.execute("DELETE FROM decided_tickets")

    second = write_workbook(tmp_path / "second.xlsx", repeats(1, 2, 3))
    with running(second, data) as relaunched:
        [proposal] = proposals(relaunched, fingerprint(relaunched))["proposals"]

    assert (proposal["status"], proposal["needs_revalidation"]) == ("not_comparable", True)


def test_answering_a_proposal_from_another_site_is_refused(tmp_path):
    path = write_workbook(tmp_path / "export.xlsx", repeats(1, 2))
    with running(path, tmp_path / "data") as booted:
        save_outcome(booted, fingerprint(booted), 2, 3, outcome="confirmed_duplicate")
        new = reimport(booted, path, repeats(1, 2, 3))
        [proposal] = proposals(booted, new)["proposals"]
        cross_site = booted.client.post(
            f"/api/snapshots/{new}/carry-forward",
            json={"id": proposal["id"], "action": "carry", "reviewer": "Alex"},
            headers={"Origin": "https://attacker.example"},
        )
        unknown = answer(booted, new, proposal, action="merge")
        still = proposals(booted, new)["proposals"]

    assert cross_site.status_code == 403
    assert unknown.status_code == 422
    assert [item["id"] for item in still] == [proposal["id"]]
