"""Ticket #37: the synthetic same-schema generator is repeatable, visibly synthetic, and plants every rule.

A generated workbook is booted like the real export; each planted pair must be
linked by the rule it was planted for, and no background ticket may be linked
at all, so the possible duplicates are exactly the planted ones.
"""

from generate import generate, write_large

from conftest import running

RULES = [
    "strict_repeat", "time_text_variant", "name_space_variant", "work_period_conflict",
    "ambiguous_period_comparison", "flagged_duplicate_counterpart", "repeated_component",
]


def test_the_same_seed_gives_the_same_workbook_and_another_seed_a_different_one():
    first, planted_first = generate(400, seed=7)
    again, planted_again = generate(400, seed=7)
    other, _ = generate(400, seed=8)

    assert first == again and planted_first == planted_again
    assert first != other
    assert len(first) == 400


def test_every_value_that_could_name_a_person_is_visibly_synthetic():
    tickets, _ = generate(2_000, seed=1)

    for values in tickets:
        assert "synthetic" in values["Employee"].casefold()
        assert values["Email Address"].endswith("@synthetic.invalid")
        assert values["Description of Job Work"].startswith("Synthetic task")
        assert values["Supervisor"].startswith("Synthetic Supervisor")
        assert values["Ticket Number"].startswith("S")


def test_the_background_carries_the_shapes_the_views_must_handle():
    tickets, _ = generate(20_000, seed=1)
    statuses = {values["Approval Status"] for values in tickets}

    assert statuses == {"Approved", "Pending", "Rejected"}
    assert any(values["Rate"] is None for values in tickets)
    assert any(values["Approval Status"] == "Approved" and not values["Keyed"] for values in tickets)
    assert any("am" not in str(values["Time"]) and "pm" not in str(values["Time"]) for values in tickets)
    assert any(values["Date"].year == 2050 for values in tickets)


def test_each_rule_links_exactly_its_planted_pair_and_nothing_else_is_linked(tmp_path):
    tickets, planted = generate(600, seed=3)
    workbook = write_large(tmp_path / "synthetic.xlsx", tickets)

    with running(workbook, tmp_path / "data") as booted:
        fingerprint = booted.get("/api/snapshot").json()["snapshot_fingerprint"]
        verdicts = {}
        for case in planted:
            body = booted.get(f"/api/snapshots/{fingerprint}/pairs/{case.first_row}/{case.second_row}").json()
            verdicts[case.rule_id] = {rule["rule_id"] for rule in body["rules"] if rule["matched"]}
        priorities = booted.get("/api/review-priorities").json()["possible_duplicates"]

    assert [case.rule_id for case in planted] == RULES
    for case in planted:
        assert case.rule_id in verdicts[case.rule_id], (case.rule_id, verdicts[case.rule_id])
    linked = sorted(sorted(member["excel_row"] for member in item["members"]) for item in priorities)
    assert linked == sorted([case.first_row, case.second_row] for case in planted)
