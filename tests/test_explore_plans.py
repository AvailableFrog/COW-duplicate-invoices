"""Ticket #16: Explore chips compile to a validated query plan, executed through the registry, drawn as a bar template."""

from collections import Counter

import openpyxl

from conftest import WORKBOOK, running
from synthetic import ticket, write_workbook

# PRD section 7's example plan, field for field.
PENDING_BY_SUPERVISOR = {
    "metric_id": "ticket_count",
    "group_by": ["Supervisor"],
    "filters": [{"field": "Approval Status", "operator": "eq", "value": "Pending"}],
    "date_basis": "Created",
    "date_range": None,
    "chart": "bar_horizontal",
    "sort": "metric_desc",
    "limit": 10,
    "include_other": True,
}


def plan(**changes):
    return {**PENDING_BY_SUPERVISOR, **changes}


def by_status():
    return plan(group_by=["Approval Status"], filters=[], chart="bar_vertical")


def source_rows():
    sheet = openpyxl.load_workbook(WORKBOOK, read_only=True).worksheets[0]
    rows = sheet.iter_rows(values_only=True)
    header = list(next(rows))
    return [dict(zip(header, row)) for row in rows]


def validate(app, body):
    response = app.client.post("/api/plans/validate", json={"plan": body})
    assert response.status_code == 200
    return response.json()


def execute(app, body, **extra):
    return app.client.post("/api/plans/execute", json={"plan": body, **extra})


def errors(result):
    return [(error["code"], error["field"]) for error in result["errors"]]


def walk_keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from walk_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk_keys(item)


# Validation


def test_the_pending_by_supervisor_plan_is_valid_and_comes_back_unchanged(app):
    result = validate(app, PENDING_BY_SUPERVISOR)

    assert result["valid"] is True
    assert result["errors"] == []
    assert result["plan"] == PENDING_BY_SUPERVISOR
    assert result["snapshot_fingerprint"] and result["versions"]["registry"]


def test_an_unknown_column_is_refused_wherever_it_appears(app):
    grouped = validate(app, plan(group_by=["Paid Amount"]))
    filtered = validate(app, plan(filters=[{"field": "Paid Date", "operator": "eq", "value": "2026-09-01"}]))

    assert grouped["valid"] is False
    assert errors(grouped) == [("unknown_field", "group_by[0]")]
    assert "Paid Amount" in grouped["errors"][0]["message"]
    assert "Supervisor" in grouped["errors"][0]["allowed"]
    assert errors(filtered) == [("unknown_field", "filters[0].field")]


def test_an_unsupported_metric_is_refused_with_the_metrics_that_are_supported(app):
    unknown = validate(app, plan(metric_id="paid_twice_count"))
    unexplorable = validate(app, plan(metric_id="unflagged_exact_repeat_count"))
    distribution = validate(app, plan(metric_id="submission_lag_days"))

    assert errors(unknown) == [("unsupported_metric", "metric_id")]
    assert "ticket_count" in unknown["errors"][0]["allowed"]
    assert "paid_twice_count" not in unknown["errors"][0]["allowed"]
    # A registry metric counting possible duplicates has no dimensions to group by.
    assert errors(unexplorable)[0] == ("unsupported_metric", "metric_id")
    # A distribution's median cannot be split into Other; its chart is a histogram, not a bar.
    assert errors(distribution) == [("unsupported_aggregation", "metric_id")]


def test_an_excessive_limit_is_refused(app):
    result = validate(app, plan(limit=500))
    zero = validate(app, plan(limit=0))

    assert errors(result) == [("limit_too_large", "limit")]
    assert "25" in result["errors"][0]["message"]
    assert errors(zero) == [("invalid_limit", "limit")]


def test_an_unsupported_operator_is_refused_with_the_operators_allowed(app):
    result = validate(app, plan(filters=[{"field": "Supervisor", "operator": "like", "value": "Brad%"}]))

    assert errors(result) == [("unsupported_operator", "filters[0].operator")]
    assert result["errors"][0]["allowed"] == ["eq", "ne", "in", "not_in"]


def test_other_plan_fields_are_checked_against_their_allowlists(app):
    result = validate(app, {
        **plan(
            group_by=["Email Address"],
            filters=[{"field": "Keyed", "operator": "in", "value": [True]}, {"field": "Approval Status", "operator": "eq", "value": "Paid"}],
            date_basis="Modified",
            chart="pie",
            sort="random",
            include_other="yes",
        ),
        "sql": "DROP TABLE tickets",
    })

    assert set(errors(result)) == {
        ("unknown_plan_field", "sql"),
        ("unsupported_dimension", "group_by[0]"),
        ("unsupported_operator", "filters[0].operator"),
        ("invalid_filter_value", "filters[1].value"),
        ("unsupported_date_basis", "date_basis"),
        ("unsupported_chart", "chart"),
        ("unsupported_sort", "sort"),
        ("invalid_plan_value", "include_other"),
    }
    missing = validate(app, {"metric_id": "ticket_count"})
    assert {code for code, _ in errors(missing)} == {"missing_plan_field"}
    assert {field for _, field in errors(missing)} == {
        "group_by", "filters", "date_basis", "date_range", "chart", "sort", "limit", "include_other",
    }


def test_values_the_database_cannot_hold_are_refused_rather_than_failing(app):
    huge = validate(app, plan(filters=[{"field": "Job Number", "operator": "eq", "value": 10**30}]))
    long_text = validate(app, plan(filters=[{"field": "Supervisor", "operator": "eq", "value": "x" * 500}]))
    bad_jobs = app.client.post("/api/plans/validate", json={"plan": PENDING_BY_SUPERVISOR, "inherited": {"jobs": ["41215"]}}).json()

    assert errors(huge) == [("invalid_filter_value", "filters[0].value")]
    assert errors(long_text) == [("invalid_filter_value", "filters[0].value")]
    assert errors(bad_jobs) == [("invalid_inherited_filter", "inherited.jobs")]


def test_a_reversed_date_range_and_two_groupings_are_refused(app):
    reversed_range = validate(app, plan(date_range={"from": "2026-10-01", "to": "2026-09-01"}))
    two = validate(app, plan(group_by=["Supervisor", "Occupation"]))

    assert errors(reversed_range) == [("invalid_date_range", "date_range")]
    assert errors(two) == [("too_many_groupings", "group_by")]


def test_executing_an_invalid_plan_is_a_recoverable_422_with_the_same_errors(app):
    response = execute(app, plan(limit=500))

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "invalid_plan"
    assert [(error["code"], error["field"]) for error in detail["errors"]] == [("limit_too_large", "limit")]


# Execution


def test_ticket_counts_by_approval_status_reconcile_with_lineage_and_versions(app):
    response = execute(app, by_status())

    assert response.status_code == 200
    body = response.json()
    groups = {group["label"]: group for group in body["result"]["groups"]}
    assert {label: group["value"] for label, group in groups.items()} == {"Approved": 2611, "Pending": 129, "Rejected": 96}
    assert body["result"]["total"] == 2836
    statuses = Counter(row["Approval Status"] for row in source_rows())
    for label, group in groups.items():
        assert len(group["excel_rows"]) == group["value"] == statuses[label]
    assert body["lineage"]["contributing_tickets"] == 2836
    assert body["lineage"]["metric"]
    # Provenance sits beside the plan, never inside it.
    assert body["plan"] == by_status()
    assert set(body["versions"]) == {"app", "registry", "rules", "parser"}
    assert body["snapshot_fingerprint"] == app.get("/api/snapshot").json()["snapshot_fingerprint"]
    assert body["as_of"]["date"] == "2026-10-08"
    assert body["grain"] == "Ticket"


def test_approved_tickets_split_by_keyed(app):
    body = execute(app, plan(
        group_by=["Keyed"], filters=[{"field": "Approval Status", "operator": "eq", "value": "Approved"}],
    )).json()

    assert [(group["key"], group["label"], group["value"]) for group in body["result"]["groups"]] == [
        (True, "true", 2462), (False, "false", 149),
    ]
    assert body["filters"]["description"] == "all dates; Approval Status is Approved"


def test_execution_is_deterministic(app):
    first = execute(app, PENDING_BY_SUPERVISOR).json()
    second = execute(app, PENDING_BY_SUPERVISOR).json()

    assert first == second


def test_pending_by_supervisor_shows_the_top_ten_and_an_explicit_other_with_the_full_table(app):
    body = execute(app, PENDING_BY_SUPERVISOR).json()

    pending = Counter(row["Supervisor"] for row in source_rows() if row["Approval Status"] == "Pending")
    table = body["result"]["groups"]
    assert {group["label"]: group["value"] for group in table} == dict(pending)
    assert sum(group["value"] for group in table) == 129
    bars = body["result"]["bars"]
    assert len(bars) == 11
    assert bars[0] == {"id": "Bradford Goodluck", "label": "Bradford Goodluck", "value": 33, "other": False}
    assert [bar["value"] for bar in bars[:10]] == sorted(pending.values(), reverse=True)[:10]
    other = bars[10]
    assert other["other"] is True
    assert other["label"] == f"Other ({len(pending) - 10} supervisors)"
    assert other["value"] == 129 - sum(sorted(pending.values(), reverse=True)[:10])
    assert sum(1 for group in table if group["in_other"]) == len(pending) - 10
    # Equal values straddle the tenth bar, so the order among them is stated rather than implied.
    assert any("same value" in warning for warning in body["warnings"])
    assert any("supervisor performance" in note for note in body["notes"])


def test_without_other_the_bars_stop_at_the_limit_and_the_table_still_holds_every_group(app):
    body = execute(app, plan(include_other=False, limit=5, sort="label_asc")).json()

    labels = [bar["label"] for bar in body["result"]["bars"]]
    assert len(labels) == 5 and labels == sorted(labels)
    assert len(body["result"]["groups"]) == 23
    assert body["result"]["hidden_groups"] == 18


def test_claimed_hours_for_the_busiest_jobs_use_the_approved_nonzero_job_scope(app):
    body = execute(app, plan(
        metric_id="claimed_hours",
        group_by=["Job Number"],
        filters=[
            {"field": "Approval Status", "operator": "eq", "value": "Approved"},
            {"field": "Job Number", "operator": "ne", "value": 0},
        ],
    )).json()

    hours = Counter()
    for row in source_rows():
        if row["Approval Status"] == "Approved" and row["Job Number"] != 0:
            hours[row["Job Number"]] += row["Regular Hours"] + row["Overtime"] + row["Double Time"]
    busiest, busiest_hours = hours.most_common(1)[0]
    first = body["result"]["bars"][0]
    assert first["value"] == busiest_hours
    assert first["label"].startswith(str(busiest))
    assert body["result"]["total"] == sum(hours.values())
    assert body["result"]["bars"][-1]["other"] is True
    assert 0 not in [group["key"] for group in body["result"]["groups"]]


def test_the_chart_is_a_trusted_vega_lite_bar_template_with_inline_data_only(app):
    body = execute(app, PENDING_BY_SUPERVISOR).json()
    chart = body["chart"]
    spec = chart["spec"]

    assert chart["template"] == "bar_horizontal"
    assert spec["$schema"].startswith("https://vega.github.io/schema/vega-lite/v6")
    assert spec["usermeta"] == {"template": "bar_horizontal"}
    assert list(spec["data"]) == ["values"]
    assert [row["label"] for row in spec["data"]["values"]] == [bar["label"] for bar in body["result"]["bars"]]
    keys = set(walk_keys(spec))
    assert not keys & {"url", "expr", "calculate", "signal", "transform", "params", "filter", "test"}
    bars = [layer for layer in spec["layer"] if layer["mark"]["type"] == "bar"]
    assert len(bars) == 1
    assert bars[0]["encoding"]["x"]["scale"]["zero"] is True
    assert bars[0]["encoding"]["x"]["scale"]["domainMin"] == 0
    assert "129 tickets" in spec["description"]

    vertical = execute(app, by_status()).json()["chart"]
    assert vertical["template"] == "bar_vertical"
    assert vertical["spec"]["layer"][1]["encoding"]["y"]["scale"]["zero"] is True


# Inherited filters and the Snapshot


def test_overview_filters_are_attached_outside_the_plan_and_narrow_it(app):
    body = execute(app, by_status(), inherited={"date_basis": "Created", "statuses": ["Pending"], "jobs": []}).json()
    all_data = execute(app, by_status(), inherited=None).json()

    assert [(group["label"], group["value"]) for group in body["result"]["groups"]] == [("Pending", 129)]
    assert body["plan"] == by_status()
    assert body["inherited_filters"]["source"] == "overview"
    assert body["inherited_filters"]["filters"]["statuses"] == ["Pending"]
    assert "Approval Status Pending" in body["filters"]["description"]
    assert all_data["inherited_filters"]["source"] == "none"
    assert all_data["result"]["total"] == 2836


def test_a_date_range_in_both_the_plan_and_the_overview_filters_is_refused_rather_than_guessed(app):
    response = execute(
        app,
        plan(date_range={"from": "2026-09-01", "to": "2026-09-30"}),
        inherited={"date_basis": "Date", "date_from": "2026-09-01", "date_to": None, "statuses": [], "jobs": []},
    )

    assert response.status_code == 422
    assert [(error["code"], error["field"]) for error in response.json()["detail"]["errors"]] == [
        ("date_range_conflict", "date_range"),
    ]


def test_a_plan_date_range_applies_to_its_date_basis(app):
    body = execute(app, plan(
        group_by=["Approval Status"], filters=[], date_basis="Date", date_range={"from": "2026-09-01", "to": "2026-09-30"},
    )).json()

    september = Counter(
        row["Approval Status"] for row in source_rows()
        if hasattr(row["Date"], "month") and (row["Date"].year, row["Date"].month) == (2026, 9)
    )
    assert {group["label"]: group["value"] for group in body["result"]["groups"]} == dict(september)
    assert body["filters"]["description"].startswith("Date as recorded from 2026-09-01 to 2026-09-30")


def test_a_new_snapshot_invalidates_a_result_until_it_is_rerun(tmp_path):
    workbook = write_workbook(tmp_path / "export.xlsx", [ticket(1), ticket(2, Approval_Status="Pending")])
    status_plan = by_status()
    with running(workbook, tmp_path) as booted:
        shown = booted.client.post("/api/plans/execute", json={"plan": status_plan}).json()
        fresh = booted.client.post(
            "/api/plans/execute", json={"plan": status_plan, "snapshot_fingerprint": shown["snapshot_fingerprint"]},
        )

        write_workbook(workbook, [ticket(1), ticket(2, Approval_Status="Pending"), ticket(3, Approval_Status="Pending")])
        assert booted.client.post("/api/snapshot/reimport").json()["imported"] is True
        stale = booted.client.post(
            "/api/plans/execute", json={"plan": status_plan, "snapshot_fingerprint": shown["snapshot_fingerprint"]},
        )
        rerun = booted.client.post("/api/plans/execute", json={"plan": status_plan}).json()

    assert fresh.status_code == 200
    assert {group["label"]: group["value"] for group in shown["result"]["groups"]} == {"Approved": 1, "Pending": 1}
    assert stale.status_code == 409
    detail = stale.json()["detail"]
    assert detail["code"] == "stale_snapshot"
    assert detail["active_snapshot_fingerprint"] == rerun["snapshot_fingerprint"] != shown["snapshot_fingerprint"]
    assert {group["label"]: group["value"] for group in rerun["result"]["groups"]} == {"Approved": 1, "Pending": 2}


# The catalogue, the starters and the provider


def test_the_catalogue_offers_six_starter_plans_that_each_validate_and_run(app):
    catalogue = app.get("/api/explore").json()

    starters = catalogue["starters"]
    assert len(starters) == 6
    assert len({starter["id"] for starter in starters}) == 6
    for starter in starters:
        assert validate(app, starter["plan"])["valid"] is True, starter["id"]
        assert execute(app, starter["plan"]).status_code == 200, starter["id"]
    by_id = {starter["id"]: starter for starter in starters}
    assert by_id["pending_by_supervisor"]["plan"] == PENDING_BY_SUPERVISOR
    metric_ids = {metric["id"] for metric in catalogue["metrics"]}
    assert {"ticket_count", "claimed_hours", "pending_count"} <= metric_ids
    assert "submission_lag_days" not in metric_ids
    assert catalogue["limits"] == {"min": 1, "max": 25, "default": 10}
    fields = {field["id"]: field for field in catalogue["fields"]}
    assert fields["Supervisor"]["operators"] == ["eq", "ne", "in", "not_in"]
    assert fields["Keyed"]["operators"] == ["eq", "ne"]
    assert {value["value"] for value in fields["Approval Status"]["values"]} == {"Approved", "Pending", "Rejected"}
    assert [chart["id"] for chart in catalogue["charts"]] == ["bar_horizontal", "bar_vertical"]


def test_the_null_provider_is_wired_and_proposes_no_plan(app):
    catalogue = app.get("/api/explore").json()
    response = app.client.post("/api/plans/propose", json={"question": "Show pending tickets by supervisor"})

    assert catalogue["provider"]["id"] == "none"
    assert response.status_code == 200
    body = response.json()
    assert body["provider"]["id"] == "none"
    assert body["plan"] is None
    assert body["validation"] is None
    assert "chips" in body["message"]
