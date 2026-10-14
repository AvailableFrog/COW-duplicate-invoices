"""Ticket #3: reimporting is idempotent by fingerprint; a different workbook is a new Snapshot."""

from conftest import HANDOFF_WORKBOOK_SHA256, running
from synthetic import ticket, without, write_workbook


def test_reimporting_the_committed_workbook_keeps_the_same_snapshot(app):
    before = app.get("/api/snapshot").json()["snapshot"]

    response = app.client.post("/api/snapshot/reimport")

    assert response.status_code == 200
    body = response.json()
    assert body["imported"] is False
    assert body["snapshot"]["fingerprint"] == HANDOFF_WORKBOOK_SHA256
    assert body["snapshot"]["imported_at"] == before["imported_at"]
    assert [s["fingerprint"] for s in app.get("/api/snapshots").json()["snapshots"]] == [HANDOFF_WORKBOOK_SHA256]


def test_a_different_workbook_at_the_launch_path_becomes_a_new_snapshot(tmp_path):
    workbook = write_workbook(tmp_path / "export.xlsx", [ticket(1), ticket(2)])
    with running(workbook, tmp_path) as booted:
        first = booted.get("/api/snapshot").json()["snapshot"]
        unchanged = booted.client.post("/api/snapshot/reimport").json()

        write_workbook(workbook, [ticket(1), ticket(2), ticket(3)])
        changed = booted.client.post("/api/snapshot/reimport").json()
        active = booted.get("/api/snapshot").json()["snapshot"]
        listed = booted.get("/api/snapshots").json()["snapshots"]
        old_row_4 = booted.get(f"/api/snapshots/{first['fingerprint']}/tickets/4")
        new_row_4 = booted.get(f"/api/snapshots/{active['fingerprint']}/tickets/4")

    assert unchanged["imported"] is False
    assert unchanged["snapshot"]["fingerprint"] == first["fingerprint"]
    assert changed["imported"] is True
    assert active["fingerprint"] == changed["snapshot"]["fingerprint"] != first["fingerprint"]
    assert active["row_count"] == 3
    assert [(s["fingerprint"], s["row_count"], s["active"]) for s in listed] == [
        (first["fingerprint"], 2, False),
        (active["fingerprint"], 3, True),
    ]
    assert old_row_4.status_code == 404
    assert new_row_4.status_code == 200


def test_a_reimport_that_cannot_be_mapped_is_refused_and_the_active_snapshot_stays(tmp_path):
    workbook = write_workbook(tmp_path / "export.xlsx", [ticket(1)])
    with running(workbook, tmp_path) as booted:
        first = booted.get("/api/snapshot").json()["snapshot"]
        write_workbook(workbook, [ticket(1)], fields=without("Ticket Number"))
        refused = booted.client.post("/api/snapshot/reimport")
        active = booted.get("/api/snapshot").json()["snapshot"]
        listed = booted.get("/api/snapshots").json()["snapshots"]

    assert refused.status_code == 422
    assert "Ticket Number" in refused.json()["detail"]
    assert active["fingerprint"] == first["fingerprint"]
    assert len(listed) == 1


def test_a_reimport_requested_by_another_site_is_refused(app):
    response = app.client.post("/api/snapshot/reimport", headers={"Origin": "https://attacker.example"})

    assert response.status_code == 403
    assert app.client.post("/api/snapshot/reimport", headers={"Origin": app.base_url}).status_code == 200
