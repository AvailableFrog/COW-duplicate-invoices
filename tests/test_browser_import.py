"""Ticket #41: importing a workbook chosen in the browser, with a preview.

The workbook is the request body of POST /api/uploads. It is stored in the
local data directory under its content's hash, imported exactly as a launch
import is, and previewed; nothing changes until it is activated. A workbook
the launch would refuse is refused with the same message and leaves the
active Snapshot as it was.
"""

import hashlib

from conftest import HANDOFF_WORKBOOK_SHA256, WORKBOOK, running
from synthetic import ticket, without, write_workbook

from labour_ticket_analytics.workbook import WorkbookError, import_workbook

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def upload(app, content, name: str = "export.xlsx", **headers):
    return app.client.post(
        "/api/uploads", content=content, headers={"Content-Type": XLSX, "X-Workbook-Name": name, **headers},
    )


def activate(app, upload_id: str, **headers):
    return app.client.post(f"/api/uploads/{upload_id}/activate", headers=headers)


def active(app) -> str:
    return app.get("/api/snapshot").json()["snapshot_fingerprint"]


def test_a_different_workbook_is_previewed_then_activated_as_a_new_snapshot_beside_the_old(tmp_path):
    chosen = write_workbook(tmp_path / "chosen.xlsx", [ticket(1), ticket(2, Approval_Status="Pending"), ticket(3)], fields=without("Rate"))
    content = chosen.read_bytes()
    data = tmp_path / "data"
    with running(WORKBOOK, data) as booted:
        previewed = upload(booted, content, name="October export.xlsx")
        still = active(booted)
        activated = activate(booted, previewed.json()["preview"]["id"])
        listed = booted.get("/api/snapshots").json()["snapshots"]
        header = booted.get("/api/snapshot").json()["snapshot"]

    assert previewed.status_code == 200, previewed.text
    preview = previewed.json()["preview"]
    assert preview["id"] == preview["fingerprint"] == hashlib.sha256(content).hexdigest()
    assert (preview["workbook_name"], preview["sheet"], preview["row_count"], preview["field_count"]) == (
        "October export.xlsx", "Labour Tickets (1)", 3, 21,
    )
    assert preview["same_as"] is None
    assert preview["missing_required_columns"] == []
    assert preview["missing_optional_columns"] == ["Rate"]
    assert {item["column"]: item["present"] for item in preview["mapping"]}["Rate"] is False
    assert {item["column"]: item["position"] for item in preview["mapping"]}["Employee"] == 1
    assert any(feature["column"] == "Rate" for feature in preview["disabled_features"])
    # Nothing changes until it is activated.
    assert still == HANDOFF_WORKBOOK_SHA256
    assert activated.status_code == 200, activated.text
    assert activated.json()["imported"] is True
    assert header["fingerprint"] == preview["fingerprint"] and header["workbook_name"] == "October export.xlsx"
    assert [(item["fingerprint"], item["active"]) for item in listed] == [
        (HANDOFF_WORKBOOK_SHA256, False), (preview["fingerprint"], True),
    ]
    # Kept in the local data directory under its hash, never beside the source.
    assert (data / "uploads" / f"{preview['fingerprint']}.xlsx").read_bytes() == content
    assert preview["stored_as"] == str((data / "uploads" / f"{preview['fingerprint']}.xlsx").resolve())


def test_identical_content_previews_as_the_active_snapshot_and_activating_it_adds_nothing(tmp_path):
    with running(WORKBOOK, tmp_path / "data") as booted:
        header = booted.get("/api/snapshot").json()["snapshot"]
        previewed = upload(booted, WORKBOOK.read_bytes(), name="Labour Tickets Export.xlsx")
        activated = activate(booted, previewed.json()["preview"]["id"])
        listed = booted.get("/api/snapshots").json()["snapshots"]

    preview = previewed.json()["preview"]
    assert preview["same_as"] == "active"
    assert (preview["row_count"], preview["field_count"], preview["import_issue_count"]) == (
        header["row_count"], header["field_count"], header["import_issue_count"],
    )
    assert sum(item["count"] for item in preview["import_issue_counts"]) == header["import_issue_count"]
    assert activated.json()["imported"] is False
    assert activated.json()["snapshot"]["imported_at"] == header["imported_at"]
    assert [item["fingerprint"] for item in listed] == [HANDOFF_WORKBOOK_SHA256]


def test_a_workbook_the_launch_would_refuse_is_refused_with_the_same_message_and_nothing_changes(tmp_path):
    chosen = write_workbook(tmp_path / "export.xlsx", [ticket(1)], fields=without("Ticket Number"))
    try:
        import_workbook(chosen)
    except WorkbookError as error:
        launch_message = str(error)
    data = tmp_path / "data"
    with running(WORKBOOK, data) as booted:
        refused = upload(booted, chosen.read_bytes(), name="export.xlsx")
        listed = booted.get("/api/snapshots").json()["snapshots"]
        now = active(booted)

    assert refused.status_code == 422
    detail = refused.json()["detail"]
    assert detail["message"] == launch_message
    assert "missing required column: Ticket Number" in detail["message"]
    assert "active Snapshot is unchanged" in detail["next_step"]
    assert now == HANDOFF_WORKBOOK_SHA256 and len(listed) == 1
    assert [path.name for path in (data / "uploads").iterdir()] == []


def test_a_file_that_is_not_an_xlsx_workbook_is_refused(tmp_path):
    with running(WORKBOOK, tmp_path / "data") as booted:
        text = upload(booted, b"Employee,Ticket Number\nAnn,L1\n", name="export.xlsx")
        csv_name = upload(booted, WORKBOOK.read_bytes(), name="export.csv")
        no_name = booted.client.post("/api/uploads", content=WORKBOOK.read_bytes(), headers={"Content-Type": XLSX})
        broken = upload(booted, b"PK\x03\x04 not really a zip", name="export.xlsx")

    assert (text.status_code, text.json()["detail"]["code"]) == (422, "not_xlsx")
    assert (csv_name.status_code, csv_name.json()["detail"]["code"]) == (422, "not_xlsx")
    assert (no_name.status_code, no_name.json()["detail"]["field"]) == (422, "name")
    assert broken.status_code == 422 and "could not be read" in broken.json()["detail"]["message"]


def test_an_upload_over_the_size_limit_is_refused_while_it_streams(tmp_path):
    def body():
        chunk = b"\0" * (1 << 20)
        for _ in range(65):
            yield chunk

    data = tmp_path / "data"
    with running(WORKBOOK, data) as booted:
        refused = upload(booted, body())

    assert refused.status_code == 413 and refused.json()["detail"]["code"] == "too_large"
    assert list((data / "uploads").iterdir()) == []


def test_uploads_and_activation_from_another_site_are_refused(tmp_path):
    with running(WORKBOOK, tmp_path / "data") as booted:
        cross_upload = upload(booted, WORKBOOK.read_bytes(), Origin="https://attacker.example")
        previewed = upload(booted, WORKBOOK.read_bytes())
        cross_activate = activate(booted, previewed.json()["preview"]["id"], Origin="https://attacker.example")
        unknown = activate(booted, "0" * 64)

    assert cross_upload.status_code == 403
    assert cross_activate.status_code == 403
    assert unknown.status_code == 404


def test_formulas_in_an_uploaded_workbook_are_kept_as_text_and_never_evaluated(tmp_path):
    chosen = write_workbook(tmp_path / "chosen.xlsx", [ticket(1, Regular_Hours="=4+4")])
    with running(WORKBOOK, tmp_path / "data") as booted:
        preview = upload(booted, chosen.read_bytes()).json()["preview"]
        activate(booted, preview["id"])
        cells = booted.get(f"/api/snapshots/{preview['id']}/tickets/2").json()["cells"]

    hours = next(cell for cell in cells if cell["field"] == "Regular Hours")
    assert (hours["raw_type"], hours["value"]) == ("formula", "=4+4")
    assert [issue["code"] for issue in preview["import_issues"]] == ["formula_not_evaluated"]


def test_saved_views_and_carry_forward_treat_an_activated_upload_as_a_new_snapshot(tmp_path):
    first = write_workbook(tmp_path / "first.xlsx", [ticket(1, Employee="Ann Smith"), ticket(2, Employee="Ann Smith")])
    second = write_workbook(tmp_path / "second.xlsx", [ticket(1, Employee="Ann Smith"), ticket(2, Employee="Ann Smith"), ticket(3)])
    with running(first, tmp_path / "data") as booted:
        old = active(booted)
        booted.client.put(
            f"/api/snapshots/{old}/pairs/2/3/outcome", json={"outcome": "confirmed_duplicate", "reviewer": "Sam"},
        )
        view = booted.client.post(
            "/api/views",
            json={"name": "All", "kind": "overview", "state": {"filters": {"date_basis": "Created", "date_from": None, "date_to": None, "jobs": [], "statuses": []}}},
        ).json()["view"]
        activate(booted, upload(booted, second.read_bytes(), name="second.xlsx").json()["preview"]["id"])
        new = active(booted)
        reopened = booted.get(f"/api/views/{view['id']}").json()["view"]
        [proposal] = booted.get(f"/api/snapshots/{new}/carry-forward").json()["proposals"]

    assert new != old
    assert [difference["field"] for difference in reopened["differences"]] == ["snapshot"]
    assert (proposal["source"]["snapshot_fingerprint"], proposal["status"]) == (old, "unchanged")
