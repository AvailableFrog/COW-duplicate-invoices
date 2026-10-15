"""Ticket #39: saved views.

A saved view is the Overview filters, or an Explore plan with its starting
filters, under a name. It records the Snapshot, as-of date, versions and
confirmed Aliases it was saved under; reopening it elsewhere reports every
difference, and nothing reruns until asked. Views live in the local review
file and survive a relaunch.
"""

from conftest import HANDOFF_WORKBOOK_SHA256, WORKBOOK, running
from synthetic import ticket, write_workbook

PENDING_BY_SUPERVISOR = {
    "metric_id": "ticket_count", "group_by": ["Supervisor"],
    "filters": [{"field": "Approval Status", "operator": "eq", "value": "Pending"}],
    "date_basis": "Created", "date_range": None, "chart": "bar_horizontal", "sort": "metric_desc",
    "limit": 10, "include_other": True,
}
OVERVIEW_STATE = {"filters": {"date_basis": "Created", "date_from": "2026-09-15", "date_to": None, "jobs": [41215], "statuses": ["Approved"]}}
EXPLORE_STATE = {"plan": PENDING_BY_SUPERVISOR, "inherited": None}


def save(app, name: str, kind: str, state: dict, **headers):
    return app.client.post("/api/views", json={"name": name, "kind": kind, "state": state}, headers=headers)


def saved(app, name: str, kind: str, state: dict) -> dict:
    response = save(app, name, kind, state)
    assert response.status_code == 200, response.text
    return response.json()["view"]


def views(app) -> list[dict]:
    response = app.get("/api/views")
    assert response.status_code == 200, response.text
    return response.json()["views"]


def test_a_saved_view_records_what_it_was_saved_under_and_is_current_where_it_was_saved(tmp_path):
    with running(WORKBOOK, tmp_path) as booted:
        view = saved(booted, "Approved on Beachlands since 15 Sep", "overview", OVERVIEW_STATE)
        listed = views(booted)

    assert view["name"] == "Approved on Beachlands since 15 Sep"
    assert view["kind"] == "overview"
    assert view["state"] == OVERVIEW_STATE
    assert view["saved_under"]["snapshot_fingerprint"] == HANDOFF_WORKBOOK_SHA256
    assert view["saved_under"]["as_of"] == "2026-10-08"
    assert set(view["saved_under"]["versions"]) == {"app", "registry", "rules", "parser"}
    assert view["saved_under"]["aliases"] == []
    assert view["current"] is True and view["differences"] == []
    assert [item["id"] for item in listed] == [view["id"]]


def test_an_explore_view_reopened_on_its_snapshot_reproduces_its_numbers(tmp_path):
    with running(WORKBOOK, tmp_path) as booted:
        before = booted.client.post("/api/plans/execute", json=EXPLORE_STATE).json()["result"]
        view = saved(booted, "Pending by supervisor", "explore", EXPLORE_STATE)
        reopened = booted.get(f"/api/views/{view['id']}").json()["view"]
        after = booted.client.post("/api/plans/execute", json=reopened["state"]).json()["result"]

    assert reopened["current"] is True
    assert after["total"] == before["total"] == 129
    assert [(bar["id"], bar["value"]) for bar in after["bars"]] == [(bar["id"], bar["value"]) for bar in before["bars"]]


def test_views_can_be_renamed_and_deleted_and_survive_a_relaunch(tmp_path):
    with running(WORKBOOK, tmp_path) as booted:
        view = saved(booted, "First name", "explore", EXPLORE_STATE)
        renamed = booted.client.put(f"/api/views/{view['id']}", json={"name": "Second name"})
        assert renamed.status_code == 200, renamed.text
        other = saved(booted, "Delete me", "overview", OVERVIEW_STATE)
        assert booted.client.delete(f"/api/views/{other['id']}").status_code == 200

    with running(WORKBOOK, tmp_path) as relaunched:
        listed = views(relaunched)
        missing = relaunched.get(f"/api/views/{other['id']}")

    assert [(item["id"], item["name"]) for item in listed] == [(view["id"], "Second name")]
    assert missing.status_code == 404


def test_a_changed_as_of_date_or_alias_is_reported_as_a_difference(tmp_path):
    with running(WORKBOOK, tmp_path) as booted:
        view = saved(booted, "Pending by supervisor", "explore", EXPLORE_STATE)
        booted.client.put("/api/as-of", json={"date": "2026-10-20"})
        booted.client.put(
            f"/api/snapshots/{HANDOFF_WORKBOOK_SHA256}/aliases",
            json={"labels": ["Mario Collymore", "Mariocollymore"], "decision": "confirmed", "reviewer": "Analyst", "rationale": "Same person"},
        )
        reopened = booted.get(f"/api/views/{view['id']}").json()["view"]

    assert reopened["current"] is False
    fields = {difference["field"]: difference for difference in reopened["differences"]}
    assert set(fields) == {"as_of", "aliases"}
    assert (fields["as_of"]["saved"], fields["as_of"]["now"]) == ("2026-10-08", "2026-10-20")
    assert "Run it again" in fields["as_of"]["message"]


def test_a_view_saved_on_another_snapshot_says_so(tmp_path):
    path = write_workbook(tmp_path / "export.xlsx", [ticket(1), ticket(2, Approval_Status="Pending")])
    with running(path, tmp_path / "data") as booted:
        view = saved(booted, "Everything", "overview", {"filters": {"date_basis": "Created", "date_from": None, "date_to": None, "jobs": [], "statuses": []}})
        write_workbook(path, [ticket(1), ticket(2), ticket(3)])
        assert booted.client.post("/api/snapshot/reimport").status_code == 200
        reopened = booted.get(f"/api/views/{view['id']}").json()["view"]

    differences = {difference["field"]: difference for difference in reopened["differences"]}
    assert reopened["current"] is False
    assert "snapshot" in differences
    assert "different export" in differences["snapshot"]["message"]


def test_invalid_views_are_refused_with_the_reason(tmp_path):
    with running(WORKBOOK, tmp_path) as booted:
        no_name = save(booted, "   ", "overview", OVERVIEW_STATE)
        long_name = save(booted, "x" * 121, "overview", OVERVIEW_STATE)
        bad_kind = save(booted, "View", "dashboard", OVERVIEW_STATE)
        bad_filter = save(booted, "View", "overview", {"filters": {**OVERVIEW_STATE["filters"], "statuses": ["Paid"]}})
        bad_plan = save(booted, "View", "explore", {"plan": {**PENDING_BY_SUPERVISOR, "metric_id": "paid_twice"}, "inherited": None})
        cross_site = save(booted, "View", "overview", OVERVIEW_STATE, Origin="https://attacker.example")
        listed = views(booted)

    assert [no_name.status_code, long_name.status_code, bad_kind.status_code] == [422, 422, 422]
    assert no_name.json()["detail"]["field"] == "name"
    assert bad_filter.status_code == 422 and bad_filter.json()["detail"]["field"].startswith("state")
    assert bad_plan.status_code == 422
    assert cross_site.status_code == 403
    assert listed == []


def test_a_view_name_is_kept_as_text_not_markup(tmp_path):
    with running(WORKBOOK, tmp_path) as booted:
        view = saved(booted, "<b>Pending</b> & co", "explore", EXPLORE_STATE)

    assert view["name"] == "<b>Pending</b> & co"


def test_a_review_file_from_before_saved_views_keeps_its_outcomes_and_gains_views(tmp_path):
    # The review file as tickets #8-#36 wrote it (schema version 2): the current schema without saved views.
    import duckdb

    from labour_ticket_analytics.review import SCHEMA

    before_views = SCHEMA.split("CREATE SEQUENCE IF NOT EXISTS saved_view_id")[0] + "CREATE TABLE IF NOT EXISTS alias_decisions" + SCHEMA.split("CREATE TABLE IF NOT EXISTS alias_decisions")[1]
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    with duckdb.connect(str(data_dir / "review.duckdb")) as connection:
        connection.execute(before_views)
        connection.execute("INSERT INTO review_store VALUES (2)")
        connection.execute(
            "INSERT INTO review_outcomes VALUES (?, 620, 855, 'L225761', 'L225526', 'needs_follow_up', 'Old note', '',"
            " 'Sam', '2026-10-14T09:00:00Z')",
            [HANDOFF_WORKBOOK_SHA256],
        )
        assert connection.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'saved_views'").fetchone()[0] == 0

    with running(WORKBOOK, data_dir) as booted:
        outcome = booted.get(f"/api/snapshots/{HANDOFF_WORKBOOK_SHA256}/pairs/620/855/outcome").json()
        view = saved(booted, "After the upgrade", "explore", EXPLORE_STATE)

    assert (outcome["outcome"]["id"], outcome["note"]) == ("needs_follow_up", "Old note")
    assert view["name"] == "After the upgrade"
