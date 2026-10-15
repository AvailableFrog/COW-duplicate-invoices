"""Ticket #17: drilldown, How calculated, relative dates, line/histogram/scatter/table, empty results, cache and CSV."""

import csv
import datetime as dt
import io
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal

import openpyxl

from conftest import WORKBOOK, running
from synthetic import Literal, ticket, write_workbook

WEEKLY_CREATED = {
    "metric_id": "ticket_count",
    "group_by": ["Week"],
    "filters": [],
    "date_basis": "Created",
    "date_range": None,
    "chart": "line",
    "sort": "label_asc",
    "limit": 10,
    "include_other": False,
}

SUBMISSION_LAG = {
    **WEEKLY_CREATED,
    "metric_id": "submission_lag_days",
    "group_by": [],
    "chart": "histogram",
}

HOURS_AGAINST_VALUE = {**SUBMISSION_LAG, "metric_id": "claimed_hours", "chart": "scatter"}

BY_STATUS = {
    **WEEKLY_CREATED,
    "group_by": ["Approval Status"],
    "chart": "bar_vertical",
    "sort": "metric_desc",
    "include_other": True,
}


def source_rows():
    sheet = openpyxl.load_workbook(WORKBOOK, read_only=True).worksheets[0]
    rows = sheet.iter_rows(values_only=True)
    header = list(next(rows))
    return [{"excel_row": index, **dict(zip(header, row))} for index, row in enumerate(rows, start=2)]


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def execute(client, plan, **extra):
    response = client.post("/api/plans/execute", json={"plan": plan, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def drilldown(client, plan, group=None, **extra):
    response = client.post("/api/plans/drilldown", json={"plan": plan, "group": group, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def errors(client, plan):
    body = client.post("/api/plans/validate", json={"plan": plan}).json()
    return {(error["code"], error["field"]) for error in body["errors"]}


def starters(app):
    return {starter["id"]: starter["plan"] for starter in app.get("/api/explore").json()["starters"]}


# Drilldown


def test_each_starter_drilldown_reproduces_its_chart_total_under_the_same_snapshot_and_versions(app):
    for starter_id, plan in starters(app).items():
        result = execute(app.client, plan)
        rows = drilldown(app.client, plan)

        assert rows["snapshot_fingerprint"] == result["snapshot_fingerprint"], starter_id
        assert rows["versions"] == result["versions"], starter_id
        assert rows["as_of"] == result["as_of"], starter_id
        assert rows["plan"] == result["plan"] == plan, starter_id
        assert rows["filters"] == result["filters"], starter_id
        if result["metric"]["statistic"] == "count":
            assert rows["tickets"] == len(rows["rows"]) == result["result"]["total"], starter_id
        else:
            assert rows["tickets"] == len(rows["rows"]) == result["result"]["contributing_tickets"], starter_id
            assert round(sum(row["value"] for row in rows["rows"]), 4) == result["result"]["total"], starter_id
        assert rows["reproduces"] is True, starter_id
        assert rows["chart_total"] == result["result"]["total"], starter_id
        # Every bar, Other included, lists exactly the tickets it counts.
        for bar in result["result"]["bars"]:
            listed = drilldown(app.client, plan, group=bar["id"])
            assert listed["group"]["id"] == bar["id"], (starter_id, bar["id"])
            assert listed["reproduces"] is True, (starter_id, bar["id"])
            assert listed["chart_total"] == bar["value"], (starter_id, bar["id"])


def test_a_bar_drilldown_lists_the_source_tickets_with_their_fields_as_recorded(app):
    plan = starters(app)["pending_by_supervisor"]
    listed = drilldown(app.client, plan, group="Bradford Goodluck")

    expected = [row for row in source_rows() if row["Approval Status"] == "Pending" and row["Supervisor"] == "Bradford Goodluck"]
    assert listed["tickets"] == len(expected) == 33
    assert [row["excel_row"] for row in listed["rows"]] == [row["excel_row"] for row in expected]
    first = listed["rows"][0]
    assert first["ticket_number"] == expected[0]["Ticket Number"]
    assert first["employee"] == expected[0]["Employee"]
    assert first["status"] == "Pending"
    assert first["supervisor"] == "Bradford Goodluck"
    assert first["description"] == expected[0]["Description of Job Work"]
    assert first["value"] is None  # a count has no per-ticket value beyond the ticket itself


def test_an_unknown_group_is_a_404_and_a_stale_snapshot_is_refused(app):
    plan = starters(app)["pending_by_supervisor"]

    unknown = app.client.post("/api/plans/drilldown", json={"plan": plan, "group": "Nobody"})
    stale = app.client.post("/api/plans/drilldown", json={"plan": plan, "group": None, "snapshot_fingerprint": "0" * 64})

    assert unknown.status_code == 404
    assert unknown.json()["detail"]["code"] == "unknown_group"
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "stale_snapshot"


# How this was calculated


def test_how_calculated_gives_the_formula_exclusions_source_rows_and_plan(app):
    plan = starters(app)["busiest_jobs"]
    body = execute(app.client, plan)
    how = body["how_calculated"]

    assert "Regular Hours + Overtime + Double Time" in how["formula"]
    assert how["statistic"] == "sum"
    assert how["plan"] == plan
    assert how["filters"] == body["filters"]["description"]
    assert how["source_rows"]["tickets"] == body["result"]["contributing_tickets"]
    assert how["source_rows"]["excel_rows"] == body["lineage"]["contributing_rows"]
    assert how["exclusion_rules"] == ["Tickets with a missing or invalid Regular Hours, Overtime or Double Time cell"]
    assert isinstance(how["exclusions"], list)
    assert "10 bars" in how["presentation"] and "Other" in how["presentation"]
    assert how["lineage"]


def test_how_calculated_lists_each_exclusion_with_its_tickets(app):
    how = execute(app.client, SUBMISSION_LAG)["how_calculated"]

    excluded = {item["code"]: item for item in how["exclusions"]}
    assert excluded["date_outside_reporting_window"]["excel_rows"] == [756, 1265, 2502]
    assert excluded["negative_lag"]["tickets"] == 16


# Relative dates


def test_last_30_days_resolves_against_the_as_of_date_and_shows_the_absolute_range(tmp_path):
    plan = {**BY_STATUS, "date_range": {"relative": "last_30_days"}}
    with running(WORKBOOK, tmp_path) as booted:
        at_default = execute(booted.client, plan)
        booted.client.put("/api/as-of", json={"date": "2026-09-30"})
        moved = execute(booted.client, plan)

    assert at_default["plan"]["date_range"] == {"relative": "last_30_days"}
    resolved = at_default["date_range"]
    assert (resolved["relative"], resolved["label"], resolved["from"], resolved["to"], resolved["as_of"]) == (
        "last_30_days", "Last 30 days", "2026-09-09", "2026-10-08", "2026-10-08",
    )
    assert resolved["date_basis"] == "Created"
    assert at_default["filters"]["description"].startswith("Created from 2026-09-09 to 2026-10-08")
    in_range = Counter(
        row["Approval Status"] for row in source_rows()
        if isinstance(row["Created"], dt.datetime) and dt.date(2026, 9, 9) <= row["Created"].date() <= dt.date(2026, 10, 8)
    )
    assert {group["label"]: group["value"] for group in at_default["result"]["groups"]} == dict(in_range)
    assert (moved["date_range"]["from"], moved["date_range"]["to"]) == ("2026-09-01", "2026-09-30")


def test_an_unknown_relative_range_is_refused_with_the_ranges_allowed(app):
    response = app.client.post("/api/plans/validate", json={"plan": {**BY_STATUS, "date_range": {"relative": "last_year"}}})

    error = response.json()["errors"][0]
    assert (error["code"], error["field"]) == ("invalid_date_range", "date_range")
    assert "last_30_days" in error["allowed"]


# Chart types


def test_weekly_created_counts_are_a_line_in_date_order(app):
    body = execute(app.client, WEEKLY_CREATED)

    weeks = Counter(
        (row["Created"].date() - dt.timedelta(days=row["Created"].weekday())).isoformat()
        for row in source_rows() if isinstance(row["Created"], dt.datetime)
    )
    groups = body["result"]["groups"]
    assert [group["key"] for group in groups] == sorted(weeks)
    assert {group["key"]: group["value"] for group in groups} == dict(weeks)
    assert body["result"]["total"] == 2836
    chart = body["chart"]
    assert chart["template"] == "line"
    assert chart["spec"]["usermeta"] == {"template": "line"}
    assert [value["key"] for value in chart["spec"]["data"]["values"]] == sorted(weeks)
    marks = [layer["mark"]["type"] for layer in chart["spec"]["layer"]]
    assert "line" in marks
    assert body["title"] == "Source records by week of Created"


def test_a_week_with_no_tickets_between_two_with_tickets_is_a_zero_and_never_skipped(tmp_path):
    workbook = write_workbook(tmp_path / "gap.xlsx", [
        ticket(1, Created=dt.datetime(2026, 9, 1, 9)),
        ticket(2, Created=dt.datetime(2026, 9, 16, 9)),
    ])
    with running(workbook, tmp_path) as booted:
        body = execute(booted.client, WEEKLY_CREATED)

    assert [(group["key"], group["value"]) for group in body["result"]["groups"]] == [
        ("2026-08-31", 1), ("2026-09-07", 0), ("2026-09-14", 1),
    ]


def test_a_line_never_connects_unordered_categories(app):
    assert ("unsupported_chart", "chart") in errors(app.client, {**BY_STATUS, "chart": "line"})


def test_dates_outside_the_reporting_window_are_listed_apart_from_the_weekly_series(app):
    body = execute(app.client, {**WEEKLY_CREATED, "date_basis": "Date", "chart": "bar_vertical"})

    outside = [group for group in body["result"]["groups"] if group["id"] == "__outside__"]
    assert len(outside) == 1
    assert outside[0]["excel_rows"] == [756, 1265, 2502]
    assert outside[0]["shown"] is False
    assert all(value["key"] != "__outside__" for value in body["chart"]["spec"]["data"]["values"])
    assert sum(group["value"] for group in body["result"]["groups"]) == body["result"]["total"] == 2836
    assert any("reporting window" in warning for warning in body["warnings"])


def test_a_submission_lag_histogram_discloses_negative_and_anomalous_records_separately(app):
    body = execute(app.client, SUBMISSION_LAG)

    lags = []
    negative = []
    outside = []
    for row in source_rows():
        work, created = row["Date"], row["Created"]
        if work.year != 2026 or created.year != 2026:
            outside.append(row["excel_row"])
        elif work.date() > created.date():
            negative.append(row["excel_row"])
        else:
            lags.append((created.date() - work.date()).days)
    assert body["result"]["total"] == len(lags) == 2817
    bins = body["result"]["groups"]
    widths = {group["bin"]["max"] - group["bin"]["min"] for group in bins}
    assert len(widths) == 1
    width = widths.pop()
    for group in bins:
        expected = sum(1 for lag in lags if group["bin"]["min"] <= lag < group["bin"]["max"])
        assert group["value"] == len(group["excel_rows"]) == expected, group["label"]
    assert sum(group["value"] for group in bins) == 2817
    assert bins[0]["bin"]["min"] == 0 and bins[-1]["bin"]["max"] > max(lags) >= bins[-1]["bin"]["max"] - width
    excluded = {item["code"]: item for item in body["coverage"]["excluded"]}
    assert excluded["date_outside_reporting_window"]["excel_rows"] == outside == [756, 1265, 2502]
    assert excluded["negative_lag"]["excel_rows"] == negative
    assert body["result"]["summary"]["median"] is not None
    assert body["chart"]["template"] == "histogram"
    drilled = drilldown(app.client, SUBMISSION_LAG, group=bins[0]["id"])
    assert drilled["tickets"] == bins[0]["value"] and drilled["reproduces"] is True


def test_a_scatterplot_plots_claimed_hours_against_base_value_for_each_priced_ticket(app):
    body = execute(app.client, HOURS_AGAINST_VALUE)

    expected = {}
    for row in source_rows():
        hours = [row["Regular Hours"], row["Overtime"], row["Double Time"]]
        if not all(number(item) for item in hours):
            continue
        total = sum(Decimal(str(item)) for item in hours)
        rate = row["Rate"]
        if not number(rate) and total != 0:
            continue
        pay = Decimal(str(row["Job Work Pay"])) if number(row["Job Work Pay"]) else Decimal(0)
        value = ((Decimal(str(rate)) if number(rate) else Decimal(0)) * total + pay).quantize(Decimal("0.01"), ROUND_HALF_UP)
        expected[row["excel_row"]] = (float(total), float(value))
    points = {point["excel_row"]: (point["x"], point["y"]) for point in body["result"]["points"]}
    assert len(points) == len(expected) == body["result"]["total"]
    assert points == expected
    assert body["chart"]["template"] == "scatter"
    assert body["paired_metric"]["id"] == "known_base_value_bbd"
    excluded = {item["code"] for item in body["coverage"]["excluded"]}
    assert "labour_unpriced" in excluded
    assert ("unsupported_chart", "chart") in errors(app.client, {**HOURS_AGAINST_VALUE, "metric_id": "ticket_count"})


def test_a_table_draws_no_chart_and_lists_every_group(app):
    body = execute(app.client, {**BY_STATUS, "group_by": ["Job Number"], "chart": "table"})

    assert body["chart"] is None
    assert body["presentation"] == "table"
    assert len(body["result"]["groups"]) == len({row["Job Number"] for row in source_rows()})


def test_the_plan_contract_refuses_charts_that_do_not_fit_the_metric_or_grouping(app):
    assert ("unsupported_chart", "chart") in errors(app.client, {**SUBMISSION_LAG, "chart": "bar_horizontal"})
    assert ("unsupported_aggregation", "group_by") in errors(app.client, {**SUBMISSION_LAG, "group_by": ["Supervisor"]})
    assert ("unsupported_chart", "chart") in errors(app.client, {**BY_STATUS, "chart": "histogram"})
    assert ("unsupported_sort", "sort") in errors(app.client, {**WEEKLY_CREATED, "sort": "metric_desc"})
    assert ("invalid_plan_value", "include_other") in errors(app.client, {**WEEKLY_CREATED, "include_other": True})


# Empty results


def test_a_plan_matching_no_tickets_is_empty_and_never_zeros(app):
    nobody = [{"field": "Supervisor", "operator": "eq", "value": "Nobody Such"}]
    bars = execute(app.client, {**BY_STATUS, "filters": nobody})
    line = execute(app.client, {**WEEKLY_CREATED, "filters": nobody})
    rows = drilldown(app.client, {**BY_STATUS, "filters": nobody})

    for body in (bars, line):
        assert body["result"]["empty"] is True
        assert body["result"]["total"] is None
        assert body["result"]["groups"] == [] and body["result"]["bars"] == []
        assert body["chart"] is None
        assert body["result"]["empty_message"]
    assert rows["rows"] == [] and rows["tickets"] == 0


# The result cache


def test_a_cached_result_is_reused_and_discarded_on_as_of_review_and_snapshot_changes(tmp_path):
    path = tmp_path / "export.xlsx"
    tickets = [ticket(1, Employee="Ann Smith"), ticket(2, Employee="Ann Smith"), ticket(3, Approval_Status="Pending")]
    write_workbook(path, tickets)
    with running(path, tmp_path) as booted:
        client = booted.client

        def status():
            return execute(client, BY_STATUS)["cache"]["status"]

        first = execute(client, BY_STATUS)
        second = execute(client, BY_STATUS)
        assert (first["cache"]["status"], second["cache"]["status"]) == ("miss", "hit")
        assert {key: value for key, value in first.items() if key != "cache"} == {
            key: value for key, value in second.items() if key != "cache"
        }
        assert first["cache"]["key"] == second["cache"]["key"]
        # The inherited filters are part of the key.
        assert execute(client, BY_STATUS, inherited={"statuses": ["Pending"]})["cache"]["status"] == "miss"
        assert drilldown(client, BY_STATUS)["cache"]["status"] == "hit"

        client.put("/api/as-of", json={"date": "2026-10-01"})
        assert status() == "miss"
        client.put("/api/as-of", json={"date": "2026-10-08"})
        assert status() == "miss"  # discarded, not merely keyed by date
        assert status() == "hit"

        fingerprint = first["snapshot_fingerprint"]
        saved = client.put(
            f"/api/snapshots/{fingerprint}/pairs/2/3/outcome", json={"outcome": "needs_follow_up", "reviewer": "Sam"},
        )
        assert saved.status_code == 200, saved.text
        after_review = execute(client, BY_STATUS)
        assert after_review["cache"]["status"] == "miss"
        assert after_review["cache"]["review_revision"] > first["cache"]["review_revision"]
        assert status() == "hit"

        write_workbook(path, [*tickets, ticket(4)])
        assert client.post("/api/snapshot/reimport").json()["imported"] is True
        assert status() == "miss"


# CSV export


def test_csv_exports_protect_formula_cells_while_the_api_returns_raw_values(tmp_path):
    workbook = write_workbook(tmp_path / "formula.xlsx", [
        ticket(1, Description_of_Job_Work=Literal('=HYPERLINK("http://example.invalid","x")'), Supervisor=Literal("=1+1")),
        ticket(2, Description_of_Job_Work=Literal("+cmd"), Supervisor="Supervisor A"),
        ticket(3, Description_of_Job_Work="-2 hours", Supervisor="@SUM(A1)"),
        ticket(4, Description_of_Job_Work="\tTabbed", Supervisor="Supervisor A"),
        ticket(5, Description_of_Job_Work="Site work", Supervisor="Supervisor A"),
    ])
    plan = {**BY_STATUS, "group_by": ["Supervisor"], "chart": "bar_horizontal"}
    with running(workbook, tmp_path) as booted:
        rows = drilldown(booted.client, plan)
        result = execute(booted.client, plan)
        table_csv = booted.client.post("/api/plans/table.csv", json={"plan": plan})
        drill_csv = booted.client.post("/api/plans/drilldown.csv", json={"plan": plan, "group": None})

    by_row = {row["excel_row"]: row for row in rows["rows"]}
    assert by_row[2]["description"] == '=HYPERLINK("http://example.invalid","x")'
    assert by_row[2]["supervisor"] == "=1+1"
    assert by_row[3]["description"] == "+cmd"
    assert "=1+1" in {group["label"] for group in result["result"]["groups"]}

    assert drill_csv.status_code == 200
    assert drill_csv.headers["content-type"].startswith("text/csv")
    assert "attachment" in drill_csv.headers["content-disposition"]
    records = list(csv.DictReader(io.StringIO(drill_csv.content.decode("utf-8-sig"))))
    descriptions = {int(record["Excel row"]): record["Description of Job Work"] for record in records}
    assert descriptions == {
        2: "'=HYPERLINK(\"http://example.invalid\",\"x\")",
        3: "'+cmd",
        4: "'-2 hours",
        5: "'\tTabbed",
        6: "Site work",
    }
    assert {int(record["Excel row"]): record["Supervisor"] for record in records}[2] == "'=1+1"
    assert {record["Snapshot"] for record in records} == {result["snapshot_fingerprint"]}

    table = list(csv.DictReader(io.StringIO(table_csv.content.decode("utf-8-sig"))))
    labels = [record["Supervisor"] for record in table]
    assert "'=1+1" in labels and "'@SUM(A1)" in labels and "=1+1" not in labels
    assert labels[-1] == "Total"
    assert table[-1]["Tickets"] == "5"
