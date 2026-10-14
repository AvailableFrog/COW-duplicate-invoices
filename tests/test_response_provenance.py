"""Ticket #4: every response carrying numbers names the Snapshot, versions and as-of date it was computed under."""

import pytest

from conftest import HANDOFF_WORKBOOK_SHA256

NUMERIC_ENDPOINTS = [
    "/api/snapshot",
    "/api/snapshots",
    f"/api/snapshots/{HANDOFF_WORKBOOK_SHA256}/tickets/2",
    "/api/metrics",
    "/api/metrics/ticket_count",
    "/api/metrics/claimed_hours?status=Pending",
    "/api/overview/tiles",
    "/api/filters",
    "/api/as-of",
]


@pytest.mark.parametrize("path", NUMERIC_ENDPOINTS)
def test_numeric_responses_carry_fingerprint_versions_and_as_of(app, path):
    body = app.get(path).json()

    assert body["snapshot_fingerprint"] == HANDOFF_WORKBOOK_SHA256
    assert {"registry", "rules", "parser"} <= body["versions"].keys()
    assert all(body["versions"][name] for name in ("registry", "rules", "parser"))
    assert body["as_of"]["date"] == "2026-10-08"


def test_the_reimport_response_carries_them_too(app):
    body = app.client.post("/api/snapshot/reimport").json()

    assert body["snapshot_fingerprint"] == HANDOFF_WORKBOOK_SHA256
    assert body["versions"]["registry"] == app.get("/api/metrics").json()["registry_version"]
    assert body["as_of"]["date"] == "2026-10-08"
