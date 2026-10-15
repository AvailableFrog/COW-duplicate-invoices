"""Ticket #13: the value-context panel, three BBD figures from the registry with their formula and completeness.

Expected values are the PRD section 9 figures (BBD 341,477.32, 3,399.71 and 571.37; 881 unpriced hours on 122
Pending Tickets) and the evidence report's C-F rows, never recomputed the way the registry does.
"""

import json

import pytest

from conftest import HANDOFF_WORKBOOK_SHA256, WORKBOOK, running
from synthetic import ticket, write_workbook

KNOWN = "known_base_value_bbd"
FLAGGED = "flagged_duplicate_base_value_bbd"
EXTRA_CLAIM = "unflagged_exact_repeat_extra_claim_bbd"
REVIEWED = "reviewed_known_base_value_bbd"
BANNED = ("paid", "saved", "lost", "liability")
# C, D, E and F: the Strict repeat rule's unflagged Approved/Keyed pairs (evidence report, pattern 1).
C_TO_F_ROWS = [[620, 855], [974, 1868], [1309, 1656], [2206, 2351]]


def panel(booted, **params) -> dict:
    response = booted.get("/api/overview/value-context", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def figure(body: dict, metric_id: str) -> dict:
    return next(item for item in body["figures"] if item["metric_id"] == metric_id)


def labels(value) -> list[str]:
    """Every `label` and `title` string anywhere in a response."""
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ("label", "title") and isinstance(item, str):
                found.append(item)
            found.extend(labels(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(labels(item))
    return found


def test_the_panel_reconciles_the_three_published_figures_from_the_registry(app):
    body = panel(app)

    assert [item["metric_id"] for item in body["figures"]] == [KNOWN, FLAGGED, EXTRA_CLAIM]
    assert [item["value"] for item in body["figures"]] == [341477.32, 3399.71, 571.37]
    assert body["currency"] == "BBD"
    for item in body["figures"]:
        registry = app.get(f"/api/metrics/{item['metric_id']}").json()
        assert item["value"] == registry["value"]
        assert item["currency"] == "BBD"
        assert item["formula"] and item["interpretation"] and item["completeness"]
    assert body["filters"]["description"] == "all dates"
    assert set(body["versions"]) == {"app", "registry", "rules", "parser"}


def test_the_known_components_disclose_881_unpriced_hours_on_122_pending_tickets(app):
    body = panel(app)
    known = figure(body, KNOWN)

    assert body["unpriced_labour"]["tickets"] == 122
    assert body["unpriced_labour"]["hours"] == 881
    assert body["unpriced_labour"]["statuses"] == [{"status": "Pending", "tickets": 122}]
    assert len(body["unpriced_labour"]["excel_rows"]) == 122
    assert body["unpriced_labour"]["summary"].startswith("881 hours across 122 Pending tickets")
    assert "881 hours" in known["completeness"]
    assert "122 Pending tickets" in known["completeness"]
    assert "never valued at zero" in known["completeness"]


def test_the_flagged_figure_values_the_28_tickets_the_tile_counts(app):
    item = figure(panel(app), FLAGGED)
    tile = app.get("/api/metrics/flagged_duplicate_count", params={"rows": "true"}).json()
    registry = app.get(f"/api/metrics/{FLAGGED}", params={"rows": "true"}).json()

    assert item["tickets"] == 28
    assert registry["contributing_rows"] == tile["contributing_rows"]


def test_the_hypothetical_figure_takes_one_whole_claim_from_each_of_c_to_f(app):
    item = figure(panel(app), EXTRA_CLAIM)
    tile = app.get("/api/metrics/unflagged_exact_repeat_count", params={"rows": "true"}).json()

    assert item["tickets"] == 8
    assert [group["excel_rows"] for group in item["possible_duplicates"]] == C_TO_F_ROWS
    assert sorted(row for group in item["possible_duplicates"] for row in group["excel_rows"]) == tile["contributing_rows"]
    assert [group["examples"] for group in item["possible_duplicates"]] == [["C"], ["D"], ["E"], ["F"]]
    assert [group["extra_claims"] for group in item["possible_duplicates"]] == [1, 1, 1, 1]
    # Peter Holder's 8 hours at 14.53; Latoya Small's 8 at 19.08; Samantha Drakes' 9 at 19.08; Mario Collymore's 9 at 14.53.
    assert [group["value"] for group in item["possible_duplicates"]] == [116.24, 152.64, 171.72, 130.77]
    assert "hypothetical" in item["label"].lower()


def test_figures_follow_the_filters(app):
    pending = panel(app, status="Pending")
    approved = panel(app, status="Approved", job=0)

    assert figure(pending, KNOWN)["value"] == app.get(f"/api/metrics/{KNOWN}", params={"status": "Pending"}).json()["value"]
    assert (figure(pending, FLAGGED)["value"], figure(pending, EXTRA_CLAIM)["value"]) == (0, 0)
    assert pending["unpriced_labour"]["tickets"] == 122
    # Approved with Job Number 0 is exactly the flagged duplicates, so the first two figures agree.
    assert figure(approved, KNOWN)["value"] == figure(approved, FLAGGED)["value"] == 3399.71
    assert approved["unpriced_labour"]["tickets"] == 0
    assert pending["filters"]["statuses"] == ["Pending"]


def test_no_label_says_paid_saved_lost_or_liability_and_the_figures_are_never_added_together(app):
    body = panel(app)
    registry = app.get("/api/metrics").json()["metrics"]
    texts = [*labels(body), *(metric["label"] for metric in registry)]
    shown = json.dumps({key: value for key, value in body.items() if key not in ("versions",)}).lower()

    assert texts and all(word not in text.lower() for text in texts for word in BANNED)
    assert not [word for word in BANNED if word in shown]
    assert "never added together" in body["note"]
    assert body["reviewed_alternative"] is None


def test_a_blank_rate_contributes_only_its_job_work_pay_and_rounding_is_half_up_per_ticket_before_summing(tmp_path):
    workbook = write_workbook(
        tmp_path / "rates.xlsx",
        [
            # 1.0025 x 2 hours = 2.005 rounds to 2.01 on each Ticket: 4.02, where rounding the sum would give 4.01.
            ticket(1, Rate=1.0025, Regular_Hours=2),
            ticket(2, Rate=1.0025, Regular_Hours=2, Time="1:00 pm to 3:00 pm"),
            # No Rate: only the Job Work Pay of 25 counts, and its 8 hours are unpriced.
            ticket(3, Rate=None, Regular_Hours=8, Job_Work_Pay=25, Approval_Status="Pending"),
        ],
    )
    with running(workbook, tmp_path) as booted:
        body = panel(booted)

    assert figure(body, KNOWN)["value"] == 29.02
    assert (body["unpriced_labour"]["tickets"], body["unpriced_labour"]["hours"]) == (1, 8)
    assert body["unpriced_labour"]["excel_rows"] == [4]
    assert "1 Pending ticket" in figure(body, KNOWN)["completeness"]


def test_the_hypothetical_counts_n_minus_1_per_strict_group_and_never_values_unpriced_labour_at_zero(tmp_path):
    def claim(number: int, employee: str, **fields):
        return ticket(number, Employee=employee, **fields)

    workbook = write_workbook(
        tmp_path / "strict.xlsx",
        [
            # Three identical claims at Rate 10: two extra claims of BBD 80 each.
            claim(1, "Ann Smith", Rate=10), claim(2, "Ann Smith", Rate=10), claim(3, "Ann Smith", Rate=10),
            # The Rate is not in the strict key: the kept claim is taken as the higher-valued one, so the extra is 80.
            claim(4, "Bob Jones", Rate=10), claim(5, "Bob Jones", Rate=12),
            # A member with no Rate: the group's extra claim cannot be valued, so it is left out and reported.
            claim(6, "Cy Lee", Rate=10), claim(7, "Cy Lee", Rate=None),
            # Pending, or holding a flagged duplicate: outside the exact repeats, not flagged.
            claim(8, "Di Ray", Approval_Status="Pending"), claim(9, "Di Ray", Approval_Status="Pending"),
            claim(10, "Ed Fox", Job_Number=0), claim(11, "Ed Fox", Job_Number=0),
        ],
    )
    with running(workbook, tmp_path) as booted:
        item = figure(panel(booted), EXTRA_CLAIM)
        tile = booted.get("/api/metrics/unflagged_exact_repeat_count").json()

    assert tile["value"] == 3
    assert [(group["excel_rows"], group["extra_claims"], group["value"]) for group in item["possible_duplicates"]] == [
        ([2, 3, 4], 2, 160), ([5, 6], 1, 80),
    ]
    assert item["value"] == 240
    [excluded] = item["coverage"]["excluded"]
    assert (excluded["code"], excluded["excel_rows"]) == ("member_labour_unpriced", [7, 8])
    assert "not valued at zero" in item["completeness"]


@pytest.fixture(scope="module")
def reviewed(tmp_path_factory):
    """The committed workbook with its own data directory, so links made here never leak into other modules."""
    with running(WORKBOOK, tmp_path_factory.mktemp("value-review")) as booted:
        yield booted


def test_an_outcome_or_note_alone_changes_nothing_and_a_kept_replaced_link_offers_a_labelled_alternative(reviewed):
    base = f"/api/snapshots/{HANDOFF_WORKBOOK_SHA256}"
    before = panel(reviewed)
    outcome = reviewed.client.put(
        f"{base}/pairs/620/855/outcome",
        json={"outcome": "needs_follow_up", "note": "Ask Oliver which one was keyed", "reviewer": "Test reviewer"},
    )
    assert outcome.status_code == 200, outcome.text
    noted = reviewed.client.put(
        f"{base}/pairs/974/1868/outcome",
        json={"outcome": "not_reviewed", "note": "Same claim twice?", "reviewer": "Test reviewer"},
    )
    assert noted.status_code == 200, noted.text

    after_outcome = panel(reviewed)
    assert after_outcome["figures"] == before["figures"]
    assert after_outcome["reviewed_alternative"] is None

    # Peter Holder's L225526 (row 855) replaced, L225761 (row 620) kept.
    link = reviewed.client.put(f"{base}/replacement-links/855/620", json={"reviewer": "Test reviewer", "rationale": ""})
    assert link.status_code == 200, link.text
    linked = panel(reviewed)
    alternative = linked["reviewed_alternative"]
    registry = reviewed.get(f"/api/metrics/{REVIEWED}").json()

    assert linked["figures"] == before["figures"]
    assert alternative["metric_id"] == REVIEWED
    assert alternative["label"].startswith("Analyst-reviewed")
    assert alternative["value"] == round(341477.32 - 116.24, 2) == registry["value"]
    assert alternative["replaced_tickets"] == [855]
    assert alternative["formula"] and alternative["interpretation"] and alternative["completeness"]
    assert {item["code"]: item["excel_rows"] for item in registry["coverage"]["excluded"]}["replaced_by_review"] == [855]
    assert all(word not in text.lower() for text in labels(alternative) for word in BANNED)

    removed = reviewed.client.request(
        "DELETE", f"{base}/replacement-links/855/620", json={"reviewer": "Test reviewer", "rationale": "Linked in error"},
    )
    assert removed.status_code == 200, removed.text
    assert panel(reviewed)["reviewed_alternative"] is None


def test_the_registry_declares_the_panel_metrics_and_which_one_reads_review_links(app):
    metrics = {metric["id"]: metric for metric in app.get("/api/metrics").json()["metrics"]}

    for metric_id in (FLAGGED, EXTRA_CLAIM, REVIEWED):
        assert metrics[metric_id]["unit"] == "BBD"
        assert metrics[metric_id]["availability"]["status"] == "available"
    assert metrics[EXTRA_CLAIM]["grain"] == "Possible duplicate"
    # The value panel's reviewed figure, and (ticket #33) the claimed-hours panel's reviewed alternative.
    assert [metric_id for metric_id, metric in metrics.items() if metric["reads_review_links"]] == [
        "reviewed_claimed_hours", REVIEWED,
    ]
