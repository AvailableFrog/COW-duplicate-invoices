"""Ticket #4: the Overview header tiles, computed through the registry and narrowed by the filter bar."""


def tile_values(body: dict) -> dict[str, int]:
    return {tile["metric_id"]: tile["value"] for tile in body["tiles"]}


def test_tiles_reproduce_the_published_counts_on_all_data(app):
    body = app.get("/api/overview/tiles").json()

    assert [(tile["label"], tile["value"]) for tile in body["tiles"]] == [
        ("Source records", 2836),
        ("Flagged duplicates", 28),
        ("Exact repeats, not flagged", 4),
        ("Pending", 129),
        ("Approved, not Keyed", 149),
    ]


def test_tiles_state_that_they_overlap_and_do_not_sum(app):
    body = app.get("/api/overview/tiles").json()

    assert "overlap" in body["note"]
    assert "do not sum" in body["note"]


def test_the_flagged_duplicate_tile_carries_olivers_qualification_in_its_definition(app):
    tiles = {tile["metric_id"]: tile for tile in app.get("/api/overview/tiles").json()["tiles"]}

    assert "more than likely" in tiles["flagged_duplicate_count"]["definition"]
    assert "Approved" in tiles["flagged_duplicate_count"]["definition"]


def test_status_breakdown_and_keyed_split_are_available_through_the_registry(app):
    statuses = app.get("/api/metrics/ticket_count", params={"group_by": "Approval Status"}).json()
    keyed = app.get("/api/metrics/ticket_count", params={"group_by": "Keyed", "status": "Approved"}).json()

    assert {group["key"]: group["value"] for group in statuses["groups"]} == {
        "Approved": 2611, "Pending": 129, "Rejected": 96,
    }
    assert statuses["value"] == 2836
    assert {group["key"]: group["value"] for group in keyed["groups"]} == {True: 2462, False: 149}


def test_a_status_filter_narrows_every_tile_consistently(app):
    pending = tile_values(app.get("/api/overview/tiles", params={"status": "Pending"}).json())
    approved = tile_values(app.get("/api/overview/tiles", params={"status": "Approved"}).json())
    rejected = tile_values(app.get("/api/overview/tiles", params={"status": "Rejected"}).json())

    assert pending == {
        "ticket_count": 129, "flagged_duplicate_count": 0, "unflagged_exact_repeat_count": 0,
        "pending_count": 129, "approved_not_keyed_count": 0,
    }
    assert approved == {
        "ticket_count": 2611, "flagged_duplicate_count": 28, "unflagged_exact_repeat_count": 4,
        "pending_count": 0, "approved_not_keyed_count": 149,
    }
    assert rejected["ticket_count"] == 96


def test_a_job_filter_narrows_the_tiles_to_that_job(app):
    job_zero = tile_values(app.get("/api/overview/tiles", params={"job": 0}).json())
    busiest_job = tile_values(app.get("/api/overview/tiles", params={"job": 40972}).json())

    assert job_zero["flagged_duplicate_count"] == 28
    assert busiest_job["ticket_count"] == 356
    assert busiest_job["flagged_duplicate_count"] == 0


def test_a_date_range_names_its_basis_and_disjoint_ranges_partition_the_records(app):
    before = app.get("/api/overview/tiles", params={"date_basis": "Created", "date_to": "2026-09-30"}).json()
    after = app.get("/api/overview/tiles", params={"date_basis": "Created", "date_from": "2026-10-01"}).json()

    assert before["filters"]["date_basis"] == {"id": "Created", "label": "Created"}
    assert before["filters"]["date_range"] == {"from": None, "to": "2026-09-30"}
    assert 0 < tile_values(before)["ticket_count"] < 2836
    assert tile_values(before)["ticket_count"] + tile_values(after)["ticket_count"] == 2836


def test_clearing_the_filters_restores_all_data_and_the_view_shows_filters_and_grain(app):
    narrowed = app.get("/api/overview/tiles", params={"status": "Pending", "job": 40972}).json()
    cleared = app.get("/api/overview/tiles").json()

    assert narrowed["filters"]["active"] is True
    assert narrowed["filters"]["statuses"] == ["Pending"]
    assert narrowed["filters"]["jobs"] == [40972]
    assert "Pending" in narrowed["filters"]["description"]
    assert cleared["filters"]["active"] is False
    assert cleared["filters"]["description"] == "all dates"
    assert cleared["grain"] == "Ticket"
    assert tile_values(cleared)["ticket_count"] == 2836


def test_a_filter_outside_the_allowlist_is_a_recoverable_error(app):
    bad_status = app.get("/api/overview/tiles", params={"status": "Paid"})
    bad_basis = app.get("/api/overview/tiles", params={"date_basis": "Modified"})
    reversed_range = app.get("/api/overview/tiles", params={"date_from": "2026-10-02", "date_to": "2026-10-01"})

    assert bad_status.status_code == 422
    assert bad_status.json()["detail"]["field"] == "status"
    assert bad_basis.json()["detail"]["field"] == "date_basis"
    assert reversed_range.json()["detail"]["field"] == "date_range"


def test_the_filter_bar_offers_date_bases_statuses_and_jobs(app):
    options = app.get("/api/filters").json()

    assert [basis["label"] for basis in options["date_bases"]] == ["Created", "Date as recorded", "Date Approved"]
    assert {status["id"]: status["tickets"] for status in options["statuses"]} == {
        "Approved": 2611, "Pending": 129, "Rejected": 96,
    }
    assert len(options["jobs"]) == 90
    assert sum(job["tickets"] for job in options["jobs"]) == 2836
