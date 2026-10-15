"""Ticket #33: claimed hours by job on the Overview, with an analyst-reviewed alternative.

The panel is a fixed Explore plan run under the Overview filters: Approved
tickets with a nonzero Job Number, grouped by job, top ten plus Other. Its
drilldowns are Explore's, so a bar lists exactly the tickets it adds up.
"""

from conftest import HANDOFF_WORKBOOK_SHA256, WORKBOOK, running

FORBIDDEN = ("productiv", "performance", "attendance", "budget", "expenditure")


def panel(app, **params) -> dict:
    response = app.get("/api/overview/claimed-hours", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def drill(app, request: dict, group: str | None) -> dict:
    response = app.client.post("/api/plans/drilldown", json={**request, "group": group})
    assert response.status_code == 200, response.text
    return response.json()


def test_the_panel_states_its_scope_in_its_title_and_draws_the_ten_busiest_jobs_plus_other(app):
    body = panel(app)

    assert body["title"] == "Claimed hours by job (Approved, Job Number not 0)"
    assert body["measure"] == "claimed_hours"
    result = body["result"]["result"]
    assert result["total"] == 17666
    assert result["contributing_tickets"] == 2583
    bars = result["bars"]
    assert len(bars) == 11 and bars[-1]["other"] is True
    assert (bars[0]["label"], bars[0]["value"]) == ("40972 Shop hill", 2536)
    assert bars[-1]["label"] == "Other (76 jobs)"
    assert body["result"]["plan"]["chart"] == "bar_horizontal"
    assert body["result"]["plan"]["limit"] == 10 and body["result"]["plan"]["include_other"] is True


def test_hours_are_shown_as_recorded_including_possible_repeats_and_never_as_productivity(app):
    body = panel(app)

    assert "including possible repeats" in body["note"]
    text = " ".join(str(body[key]) for key in ("title", "question", "note")).casefold()
    text += " ".join(measure["label"] for measure in body["measures"]).casefold()
    assert not [word for word in FORBIDDEN if word in text]


def test_the_measure_switches_to_ticket_count_and_anything_else_is_a_recoverable_error(app):
    by_tickets = panel(app, measure="ticket_count")
    refused = app.get("/api/overview/claimed-hours", params={"measure": "employee_label_count"})

    assert [measure["id"] for measure in by_tickets["measures"]] == ["claimed_hours", "ticket_count"]
    assert by_tickets["measure"] == "ticket_count"
    assert by_tickets["result"]["result"]["total"] == 2583  # 2,611 Approved less the 28 flagged duplicates
    assert by_tickets["title"] == "Tickets by job (Approved, Job Number not 0)"
    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "unknown_measure"


def test_every_bar_and_other_drills_down_to_exactly_what_it_adds_up(app):
    body = panel(app)
    request = body["request"]

    whole = drill(app, request, None)
    assert whole["reproduces"] is True and whole["chart_total"] == 17666
    for bar in body["result"]["result"]["bars"]:
        listed = drill(app, request, bar["id"])
        assert listed["reproduces"] is True, bar["id"]
        assert listed["chart_total"] == bar["value"], bar["id"]
        for key in ("snapshot_fingerprint", "versions", "as_of", "filters"):
            assert listed[key] == body["result"][key], key


def test_the_panel_follows_the_overview_filters(app):
    one_job = panel(app, job=41215)
    pending = panel(app, status="Pending")

    assert [bar["id"] for bar in one_job["result"]["result"]["bars"]] == ["41215"]
    assert one_job["result"]["filters"]["jobs"] == [41215]
    # The panel's scope is Approved tickets, so a Pending filter leaves nothing: an empty state, never a zero.
    assert pending["result"]["result"]["empty"] is True
    assert "not a zero" in pending["result"]["result"]["empty_message"]


def test_no_reviewed_alternative_appears_without_a_kept_replaced_link(app):
    assert panel(app)["reviewed"] is None


def test_a_kept_replaced_link_offers_a_labelled_reviewed_alternative_and_an_outcome_alone_does_not(tmp_path):
    with running(WORKBOOK, tmp_path) as booted:
        base = f"/api/snapshots/{HANDOFF_WORKBOOK_SHA256}"
        outcome = booted.client.put(
            f"{base}/pairs/620/855/outcome",
            json={"outcome": "confirmed_duplicate", "reviewer": "Analyst", "note": "Same claim twice"},
        )
        assert outcome.status_code == 200, outcome.text
        assert panel(booted)["reviewed"] is None

        linked = booted.client.put(
            f"{base}/replacement-links/620/855", json={"reviewer": "Analyst", "rationale": "620 repeats 855"},
        )
        assert linked.status_code == 200, linked.text
        body = panel(booted)

    reviewed = body["reviewed"]
    assert reviewed is not None
    assert reviewed["label"].startswith("Analyst-reviewed alternative")
    assert reviewed["replaced_tickets"] == 1
    assert reviewed["result"]["plan"]["metric_id"] == "reviewed_claimed_hours"
    # Row 620 (Peter Holder, 8 hours on job 41215) is left out; everything else is unchanged.
    assert reviewed["result"]["result"]["total"] == body["result"]["result"]["total"] - 8 == 17658
