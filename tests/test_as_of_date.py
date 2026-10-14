"""Ticket #4: the analytical as-of date defaults to 8 October 2026, is an assumption, and can be changed."""

from conftest import WORKBOOK, running


def test_the_as_of_date_defaults_to_8_october_2026_labelled_as_an_assumption(app):
    as_of = app.get("/api/as-of").json()["as_of"]

    assert as_of["date"] == "2026-10-08"
    assert as_of["is_assumption"] is True
    assert as_of["is_default"] is True
    assert "assumption" in as_of["note"]


def test_changing_the_as_of_date_is_reflected_in_subsequent_responses(tmp_path):
    with running(WORKBOOK, tmp_path) as booted:
        before = booted.get("/api/metrics/pending_submission_age_days").json()
        changed = booted.client.put("/api/as-of", json={"date": "2026-10-18"})
        after = booted.get("/api/metrics/pending_submission_age_days").json()
        tiles = booted.get("/api/overview/tiles").json()
        header = booted.get("/api/snapshot").json()

    assert changed.status_code == 200
    assert changed.json()["as_of"]["date"] == "2026-10-18"
    assert before["as_of"]["date"] == "2026-10-08"
    assert before["summary"]["count"] == after["summary"]["count"] == 129
    assert before["summary"]["min"] == 0
    assert after["summary"]["min"] == 10
    assert after["summary"]["max"] == before["summary"]["max"] + 10
    for body in (after, tiles, header):
        assert body["as_of"]["date"] == "2026-10-18"
        assert body["as_of"]["is_assumption"] is True
        assert body["as_of"]["is_default"] is False


def test_an_as_of_date_before_a_submission_reports_it_rather_than_ageing_it_from_zero(tmp_path):
    with running(WORKBOOK, tmp_path) as booted:
        booted.client.put("/api/as-of", json={"date": "2026-09-01"})
        body = booted.get("/api/metrics/pending_submission_age_days").json()

    excluded = {item["code"]: item["tickets"] for item in body["coverage"]["excluded"]}
    assert excluded == {"created_after_as_of": 129}
    assert body["value"] is None
    assert body["warnings"]


def test_another_site_cannot_change_the_as_of_date(app):
    refused = app.client.put("/api/as-of", json={"date": "2026-01-01"}, headers={"Origin": "https://attacker.example"})

    assert refused.status_code == 403
    assert app.get("/api/as-of").json()["as_of"]["date"] == "2026-10-08"


def test_an_unreadable_as_of_date_is_refused(app):
    assert app.client.put("/api/as-of", json={"date": "08/10/2026"}).status_code == 422
    assert app.get("/api/as-of").json()["as_of"]["date"] == "2026-10-08"
