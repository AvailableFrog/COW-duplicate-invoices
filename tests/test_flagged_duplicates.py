"""Ticket #11: the Flagged-duplicate counterpart and Repeated component rules, and the Flagged duplicates view.

Expected values come from the evidence report's examples H, I, K and M
(docs/source/labour-ticket-report-readable.md), PRD sections 4 and 5, and the
committed workbook's 28 Approved / Job Number 0 rows. Shapes the export lacks
are built with tests/synthetic.py.
"""

from conftest import HANDOFF_WORKBOOK_SHA256, running
from synthetic import ticket, write_workbook

# The flagged duplicates whose counterparts the PRD section 5 predicate finds in the export: the same
# employee and Date with the same four hour and pay amounts, the same Confident Intervals, or (K alone)
# the same unresolved Time text and description. The other twelve have none.
COUNTERPART_FOUND = {318, 398, 877, 889, 1077, 1083, 1204, 1341, 1515, 1643, 1749, 1970, 2044, 2163, 2179, 2188}


def evidence(app, excel_row: int, fingerprint: str = HANDOFF_WORKBOOK_SHA256) -> dict:
    response = app.get(f"/api/snapshots/{fingerprint}/tickets/{excel_row}/possible-duplicate")
    assert response.status_code == 200, response.text
    return response.json()


def flagged(app, **params) -> dict:
    response = app.get("/api/flagged-duplicates", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def entry(body: dict, excel_row: int) -> dict:
    return next(item for item in body["flagged_duplicates"] if item["excel_row"] == excel_row)


def candidates(payload: dict, rule_id: str) -> list[dict]:
    return [candidate for candidate in payload["candidates"] if candidate["rule_id"] == rule_id]


def member_rows(payload: dict) -> set[int]:
    return {member["excel_row"] for member in payload["members"]}


def verdict(app, first: int, second: int, rule_id: str, fingerprint: str = HANDOFF_WORKBOOK_SHA256) -> dict:
    response = app.get(f"/api/snapshots/{fingerprint}/pairs/{first}/{second}")
    assert response.status_code == 200, response.text
    return next(rule for rule in response.json()["rules"] if rule["rule_id"] == rule_id)


def fingerprint_of(booted) -> str:
    return booted.get("/api/snapshot").json()["snapshot_fingerprint"]


def test_the_flagged_duplicates_tile_shows_28_with_olivers_qualification(app):
    tiles = {tile["metric_id"]: tile for tile in app.get("/api/overview/tiles").json()["tiles"]}

    tile = tiles["flagged_duplicate_count"]
    assert (tile["label"], tile["value"], tile["unit"]) == ("Flagged duplicates", 28, "tickets")
    assert "more than likely a duplicate" in tile["definition"]


def test_the_flagged_duplicates_list_holds_all_28_with_counterpart_found_or_unresolved_for_each(app):
    body = flagged(app)
    metric = app.get("/api/metrics/flagged_duplicate_count", params={"rows": "true"}).json()

    listed = body["flagged_duplicates"]
    assert sorted(item["excel_row"] for item in listed) == metric["contributing_rows"]
    assert len(listed) == 28
    assert all((item["status"], item["job_number"], item["flagged_duplicate"]) == ("Approved", 0, True) for item in listed)
    found = {item["excel_row"] for item in listed if item["counterpart_status"]["id"] == "counterpart_found"}
    unresolved = {item["excel_row"] for item in listed if item["counterpart_status"]["id"] == "unresolved"}
    assert found == COUNTERPART_FOUND
    assert len(unresolved) == 12 and not found & unresolved
    assert {item["counterpart_status"]["label"] for item in listed} == {"Counterpart found", "Unresolved"}
    # Shown separately from the tile: the list says how its 28 split, and the tile stays one count.
    assert body["counts"] == {"flagged_duplicates": 28, "counterpart_found": 16, "unresolved": 12}
    assert body["metric_id"] == "flagged_duplicate_count"
    assert all(bool(item["counterparts"]) == (item["excel_row"] in found) for item in listed)


def test_the_list_follows_the_filters_like_the_tile(app):
    pending = flagged(app, status="Pending")
    job = flagged(app, job=0)

    assert pending["flagged_duplicates"] == [] and pending["counts"]["flagged_duplicates"] == 0
    assert job["counts"]["flagged_duplicates"] == 28


# K. Errol Thornhill, rows 2188 (Job 0) / 2187: same Time "7:30-4:30" and description "Boxing", hours changed.
def test_k_is_an_uncertain_counterpart_through_identical_unresolved_time_text_and_description(app):
    k = evidence(app, 2188)

    [counterpart] = candidates(k, "flagged_duplicate_counterpart")
    assert counterpart["excel_rows"] == [2187, 2188]
    assert counterpart["rule_label"] == "Flagged-duplicate counterpart"
    assert counterpart["evidence_strength"] == "weak"
    assert "Uncertain counterpart" in counterpart["reason"]
    assert "7:30-4:30" in counterpart["reason"]
    assert "description" in counterpart["reason"]
    assert "Regular Hours and Double Time differ" in counterpart["reason"]
    # The AM/PM reading stays unresolved: compared only under the assumed readings.
    assert "AM/PM" in counterpart["reason"]
    assert counterpart["time_comparison"]["result"] == "ambiguous"
    assert counterpart["time_comparison"]["assumed"] is True
    assert {m["excel_row"]: m["time_parse"]["status"] for m in k["members"]} == {2187: "ambiguous", 2188: "ambiguous"}

    listed = entry(flagged(app), 2188)
    assert listed["counterpart_status"]["id"] == "counterpart_found"
    assert [(c["excel_row"], c["certain"]) for c in listed["counterparts"]] == [(2187, False)]


def test_a_counterpart_is_found_on_any_job_and_every_plausible_counterpart_is_listed(tmp_path):
    workbook = write_workbook(tmp_path / "counterparts.xlsx", [
        # Row 2, the flagged duplicate; rows 3 and 4 repeat its claim on two different jobs and sites.
        ticket(1, Employee="Ann Smith", Job_Number=0, Job_Name="Sandals"),
        ticket(2, Employee="Ann Smith", Job_Number=41215, Job_Name="Sandals"),
        ticket(3, Employee="Ann Smith", Job_Number=40000, Job_Name="Beachlands"),
        # Row 5: the same day but another claim and other hours; it overlaps, but is no counterpart.
        ticket(4, Employee="Ann Smith", Time="1:00 pm to 5:00 pm", Regular_Hours=4),
        # Rows 6/7: the same Confident Interval written differently, with different hours.
        ticket(5, Employee="Bob Jones", Job_Number=0, Time="7:30am-4:30pm", Overtime=1),
        ticket(6, Employee="Bob Jones", Time="7:30 am - 4:30 pm"),
        # Rows 8/9: a Pending ticket on Job 0 is not a flagged duplicate.
        ticket(7, Employee="Dee Ray", Job_Number=0, Approval_Status="Pending", Keyed=False),
        ticket(8, Employee="Dee Ray"),
    ])

    with running(workbook, tmp_path) as booted:
        fingerprint = fingerprint_of(booted)
        ann = evidence(booted, 2, fingerprint)
        bob = evidence(booted, 6, fingerprint)
        body = flagged(booted)
        dee = verdict(booted, 8, 9, "flagged_duplicate_counterpart", fingerprint)

    assert [c["excel_rows"] for c in candidates(ann, "flagged_duplicate_counterpart")] == [[2, 3], [2, 4]]
    assert all(c["evidence_strength"] == "moderate" for c in candidates(ann, "flagged_duplicate_counterpart"))
    assert member_rows(ann) == {2, 3, 4, 5}
    [ann_entry] = [item for item in body["flagged_duplicates"] if item["excel_row"] == 2]
    assert [c["excel_row"] for c in ann_entry["counterparts"]] == [3, 4]
    assert all(c["certain"] for c in ann_entry["counterparts"])
    # No counterpart is chosen as the original, and no job is recovered from Job Name.
    reason = candidates(ann, "flagged_duplicate_counterpart")[0]["reason"]
    assert "Job Number is not compared" in reason and "none is chosen as the original" in reason
    [bob_link] = candidates(bob, "flagged_duplicate_counterpart")
    assert "same work periods (07:30-16:30)" in bob_link["reason"]
    assert bob_link["evidence_strength"] == "moderate"
    assert dee["matched"] is False and "flagged duplicate" in dee["reason"]
    assert [item["excel_row"] for item in body["flagged_duplicates"]] == [2, 6]


def test_an_unresolved_time_needs_the_same_nonempty_description_to_be_an_uncertain_counterpart(tmp_path):
    workbook = write_workbook(tmp_path / "uncertain.xlsx", [
        ticket(1, Employee="Cy Lee", Job_Number=0, Time="7:30-4:30", Description_of_Job_Work="Boxing"),
        ticket(2, Employee="Cy Lee", Time=" 7:30-4:30", Regular_Hours=0, Double_Time=9, Description_of_Job_Work=" boxing "),
        ticket(3, Employee="Eve Hart", Job_Number=0, Time="7:30-4:30", Description_of_Job_Work="Boxing"),
        ticket(4, Employee="Eve Hart", Time="7:30-4:30", Regular_Hours=0, Double_Time=9, Description_of_Job_Work="Framing"),
        ticket(5, Employee="Fay Lim", Job_Number=0, Time="7:30-4:30", Description_of_Job_Work=None),
        ticket(6, Employee="Fay Lim", Time="7:30-4:30", Regular_Hours=0, Double_Time=9, Description_of_Job_Work=None),
    ])

    with running(workbook, tmp_path) as booted:
        fingerprint = fingerprint_of(booted)
        cy = verdict(booted, 2, 3, "flagged_duplicate_counterpart", fingerprint)
        eve = verdict(booted, 4, 5, "flagged_duplicate_counterpart", fingerprint)
        fay = verdict(booted, 6, 7, "flagged_duplicate_counterpart", fingerprint)

    assert cy["matched"] is True and cy["evidence_strength"] == "weak"
    assert eve["matched"] is False
    assert fay["matched"] is False


# M. Weston Holder, rows 1575 / 2149: both Approved / Job 0, both Job Work Pay 50; 1575 claims no hours.
def test_m_is_a_low_confidence_repeated_component_and_the_no_hours_ticket_was_created_later(app):
    m = evidence(app, 1575)

    [component] = candidates(m, "repeated_component")
    assert component["excel_rows"] == [1575, 2149]
    assert component["rule_label"] == "Repeated component"
    assert component["evidence_strength"] == "weak"
    assert component["pattern"] == "Repeated payment component"
    assert "low-confidence component comparison" in component["reason"]
    assert "entitlement" not in component["reason"]
    assert "Repeated payment component" in m["pattern_labels"]
    # Neither is a counterpart of the other: no hour vector, work periods or unresolved text in common.
    assert [c for c in m["candidates"] if c["rule_id"] == "flagged_duplicate_counterpart"] == []

    timeline = m["timeline"]
    hours = timeline["fields"].index("Regular Hours")
    created = timeline["fields"].index("Created")
    order = [(e["excel_row"], e["cells"][created]["value"], e["cells"][hours]["value"]) for e in timeline["entries"]]
    with_hours, no_hours = (next(item for item in order if item[0] == row) for row in (2149, 1575))
    assert (with_hours[1], with_hours[2]) == ("2026-09-15T17:01:00", 2)
    assert (no_hours[1], no_hours[2]) == ("2026-09-21T17:15:00", 0)
    assert order.index(with_hours) < order.index(no_hours)

    body = flagged(app)
    for row in (1575, 2149):
        assert entry(body, row)["counterpart_status"]["id"] == "unresolved"
        assert entry(body, row)["possible_duplicate"]["display_id"] == m["display_id"]


def test_the_repeated_component_needs_equal_positive_job_work_pay_on_one_job_or_beside_job_0(tmp_path):
    morning, afternoon = "7:30am-9:30am", "1:00pm-3:00pm"
    workbook = write_workbook(tmp_path / "components.xlsx", [
        ticket(1, Employee="Eve Hart", Job_Work_Pay=25, Regular_Hours=2, Time=morning),
        ticket(2, Employee="Eve Hart", Job_Work_Pay=25, Regular_Hours=2, Time=afternoon),
        ticket(3, Employee="Fay Lim", Job_Work_Pay=25, Regular_Hours=2, Time=morning),
        ticket(4, Employee="Fay Lim", Job_Work_Pay=25, Regular_Hours=2, Time=afternoon, Job_Number=40000),
        ticket(5, Employee="Gus Moe", Job_Work_Pay=30, Regular_Hours=0, Time=morning, Job_Number=0),
        ticket(6, Employee="Gus Moe", Job_Work_Pay=30, Regular_Hours=2, Time=afternoon),
        ticket(7, Employee="Hal Ng", Job_Work_Pay=0, Regular_Hours=2, Time=morning),
        ticket(8, Employee="Hal Ng", Job_Work_Pay=0, Regular_Hours=2, Time=afternoon),
    ])

    with running(workbook, tmp_path) as booted:
        fingerprint = fingerprint_of(booted)
        same_job, other_jobs, beside_zero, no_pay = (
            verdict(booted, first, first + 1, "repeated_component", fingerprint) for first in (2, 4, 6, 8)
        )
        priorities = booted.get("/api/review-priorities").json()["possible_duplicates"]

    assert same_job["matched"] is True and "same job" in same_job["reason"]
    assert other_jobs["matched"] is False
    assert beside_zero["matched"] is True and "Job Number 0" in beside_zero["reason"]
    assert no_pay["matched"] is False
    # Only the Repeated component links these pairs, so it alone makes each a possible duplicate.
    assert sorted(sorted(member_rows(item)) for item in priorities) == [[2, 3], [6, 7]]
    assert {item["tier"]["rank"] for item in priorities if member_rows(item) == {2, 3}} == {2}


# I. Damar Graham: 318 Approved / Job 0, 1545 Approved, 999 Rejected; same Date, Time and hours.
def test_i_holds_rejected_row_999_as_context_with_318_and_1545_and_shows_the_chronology(app):
    i = evidence(app, 318)

    assert member_rows(i) == {318, 999, 1545}
    assert sorted(c["excel_rows"] for c in candidates(i, "flagged_duplicate_counterpart")) == [[318, 999], [318, 1545]]
    assert [c["excel_rows"] for c in candidates(i, "strict_repeat")] == [[999, 1545]]
    assert {m["excel_row"]: m["status"] for m in i["members"]} == {318: "Approved", 999: "Rejected", 1545: "Approved"}
    assert i["tier"]["rank"] == 3
    timeline = i["timeline"]
    supervisor = timeline["fields"].index("Supervisor")
    status = timeline["fields"].index("Approval Status")
    assert [
        (e["excel_row"], e["cells"][status]["value"], e["cells"][supervisor]["value"]) for e in timeline["entries"]
    ] == [(1545, "Approved", "Troy Small"), (999, "Rejected", "Troy Small"), (318, "Approved", "Troy Small")]
    assert {"Occupation", "Job Name", "Description of Job Work", "Modified By"} <= set(i["differing_fields"])

    listed = entry(flagged(app), 318)
    assert [(c["excel_row"], c["status"], c["certain"]) for c in listed["counterparts"]] == [
        (999, "Rejected", True), (1545, "Approved", True),
    ]


# H. Mario Collymore / Mariocollymore, rows 829 (Approved) / 1072 (Pending).
def test_hs_drawer_shows_the_pending_ticket_was_created_before_the_approved_one(app):
    timeline = evidence(app, 829)["timeline"]

    created = timeline["fields"].index("Created")
    status = timeline["fields"].index("Approval Status")
    assert [
        (e["excel_row"], e["cells"][status]["value"], e["cells"][created]["value"]) for e in timeline["entries"]
    ] == [(1072, "Pending", "2026-09-27T19:41:00"), (829, "Approved", "2026-09-29T09:31:00")]


def test_a_flagged_duplicate_with_several_counterparts_in_the_export_lists_every_one(app):
    body = flagged(app)

    assert [c["excel_row"] for c in entry(body, 2163)["counterparts"]] == [2169, 2172, 2224]
    assert [c["excel_row"] for c in entry(body, 1643)["counterparts"]] == [1641, 1649]


def test_possible_duplicates_holding_a_flagged_duplicate_with_an_unresolved_counterpart_are_in_the_third_tier(app):
    ranked = app.get("/api/review-priorities").json()["possible_duplicates"]

    holding = [item for item in ranked if any(m["flagged_duplicate"] for m in item["members"])]
    assert {item["tier"]["rank"] for item in holding} == {3}
    assert {2188, 1575, 318} <= {m["excel_row"] for item in holding for m in item["members"]}
    assert all(not item["exact_repeat_not_flagged"] for item in holding)
    # C-F still lead, and the exact-repeat tile still reads 4 / 8.
    assert [member_rows(item) for item in ranked[:4]] == [{2206, 2351}, {974, 1868}, {1309, 1656}, {620, 855}]
    tiles = {tile["metric_id"]: tile for tile in app.get("/api/overview/tiles").json()["tiles"]}
    assert (tiles["unflagged_exact_repeat_count"]["value"], tiles["unflagged_exact_repeat_count"]["tickets"]) == (4, 8)


def save_outcome(app, fingerprint: str, first: int, second: int, outcome: str, rationale: str = "") -> None:
    response = app.client.put(
        f"/api/snapshots/{fingerprint}/pairs/{first}/{second}/outcome",
        json={"outcome": outcome, "reviewer": "Test reviewer", "note": "", "reference": "", "rationale": rationale},
    )
    assert response.status_code == 200, response.text


def tier_of(app, excel_row: int) -> int:
    ranked = app.get("/api/review-priorities").json()["possible_duplicates"]
    return next(item["tier"]["rank"] for item in ranked if excel_row in member_rows(item))


def test_a_reviewer_settles_a_counterpart_with_a_confirmed_duplicate_replacement_or_link_and_it_leaves_tier_3(tmp_path):
    morning, afternoon = "7:30am-9:30am", "1:00pm-3:00pm"
    workbook = write_workbook(tmp_path / "settled.xlsx", [
        ticket(1, Employee="Ann Smith", Job_Number=0),
        ticket(2, Employee="Ann Smith"),
        ticket(3, Employee="Bob Jones", Job_Number=0),
        ticket(4, Employee="Bob Jones"),
        # Rows 6/7: linked only by the Repeated component, so neither flagged duplicate has a counterpart.
        ticket(5, Employee="Gus Moe", Job_Number=0, Job_Work_Pay=30, Regular_Hours=0, Time=morning),
        ticket(6, Employee="Gus Moe", Job_Number=0, Job_Work_Pay=30, Regular_Hours=2, Time=afternoon),
    ])

    with running(workbook, tmp_path) as booted:
        fingerprint = fingerprint_of(booted)
        assert [tier_of(booted, row) for row in (2, 4, 6)] == [3, 3, 3]

        save_outcome(booted, fingerprint, 2, 3, "not_a_duplicate")
        save_outcome(booted, fingerprint, 6, 7, "confirmed_duplicate")
        assert [tier_of(booted, row) for row in (2, 6)] == [3, 3]
        assert entry(flagged(booted), 2)["settled_by_review"] is False

        save_outcome(booted, fingerprint, 2, 3, "confirmed_duplicate", rationale="Same claim after all")
        link = booted.client.put(
            f"/api/snapshots/{fingerprint}/replacement-links/4/5", json={"reviewer": "Test reviewer", "rationale": ""},
        )
        assert link.status_code == 200, link.text
        body = flagged(booted)
        ann_tier, bob_tier, gus_tier = (tier_of(booted, row) for row in (2, 4, 6))
        drawer_tier = evidence(booted, 2, fingerprint)["tier"]["rank"]

    assert (ann_tier, bob_tier, gus_tier, drawer_tier) == (4, 4, 3, 4)
    assert [(item["excel_row"], item["settled_by_review"]) for item in body["flagged_duplicates"]] == [
        (2, True), (4, True), (6, False), (7, False),
    ]
    [counterpart] = entry(body, 2)["counterparts"]
    assert counterpart["outcome"] == {"id": "confirmed_duplicate", "label": "Confirmed duplicate"}


def test_a_flagged_duplicate_in_no_possible_duplicate_still_opens_its_own_evidence(app):
    base = f"/api/snapshots/{HANDOFF_WORKBOOK_SHA256}/tickets"
    alone = app.get(f"{base}/279/evidence")
    linked = app.get(f"{base}/318/evidence")

    assert alone.status_code == 200, alone.text
    body = alone.json()
    assert [(m["excel_row"], m["flagged_duplicate"]) for m in body["members"]] == [(279, True)]
    assert body["possible_duplicate"] is None
    assert len(body["fields"]) == 22 and body["timeline"]["entries"][0]["excel_row"] == 279
    assert entry(flagged(app), 279)["possible_duplicate"] is None
    assert linked.json()["possible_duplicate"] == evidence(app, 318)["display_id"]
    assert app.get(f"{base}/2838/evidence").status_code == 404


def test_the_two_rules_are_described_and_accept_a_confirmed_alias(app):
    rules = {rule["id"]: rule for rule in app.get("/api/review-priorities").json()["rules"]}

    assert list(rules)[-2:] == ["flagged_duplicate_counterpart", "repeated_component"]
    assert [rule_id for rule_id, rule in rules.items() if rule["accepts_alias"]] == [
        "work_period_conflict", "flagged_duplicate_counterpart", "repeated_component",
    ]
    assert rules["repeated_component"]["evidence_strength"] == "weak"
    assert rules["repeated_component"]["pattern"] == "Repeated payment component"
    assert rules["flagged_duplicate_counterpart"]["pattern"] == "Possible correction or resubmission"
    assert "Description of Job Work" in rules["flagged_duplicate_counterpart"]["fields_compared"]
    assert "Job Number" not in rules["flagged_duplicate_counterpart"]["fields_compared"]


def test_a_confirmed_alias_widens_both_rules(tmp_path):
    workbook = write_workbook(tmp_path / "alias.xlsx", [
        # The Name-space variant proposes the Alias from rows 2/3.
        ticket(1, Employee="Mario Collymore"),
        ticket(2, Employee="Mariocollymore"),
        # Row 4 is a flagged duplicate of row 5 under the other label, with the same task payment too.
        ticket(3, Employee="Mario Collymore", Job_Number=0, Date=ticket()["Date"].replace(day=27), Job_Work_Pay=20),
        ticket(4, Employee="Mariocollymore", Date=ticket()["Date"].replace(day=27), Job_Work_Pay=20),
    ])

    with running(workbook, tmp_path) as booted:
        fingerprint = fingerprint_of(booted)
        before = {rule: verdict(booted, 4, 5, rule, fingerprint)["matched"] for rule in ("flagged_duplicate_counterpart", "repeated_component")}
        response = booted.client.put(
            f"/api/snapshots/{fingerprint}/aliases",
            json={"labels": ["Mario Collymore", "Mariocollymore"], "decision": "confirmed", "reviewer": "Test", "rationale": "Same person"},
        )
        assert response.status_code == 200, response.text
        after = {rule: verdict(booted, 4, 5, rule, fingerprint)["matched"] for rule in ("flagged_duplicate_counterpart", "repeated_component")}
        listed = flagged(booted)

    assert before == {"flagged_duplicate_counterpart": False, "repeated_component": False}
    assert after == {"flagged_duplicate_counterpart": True, "repeated_component": True}
    assert [c["excel_row"] for c in entry(listed, 4)["counterparts"]] == [5]
