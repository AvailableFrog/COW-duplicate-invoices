"""Ticket #3: a workbook missing an optional column loads with the dependent features disabled and explained."""

from conftest import boot, shutdown
from synthetic import ticket, without, write_workbook


def header_for(workbook, data_dir) -> dict:
    booted = boot(workbook, data_dir)
    try:
        return booted.get("/api/snapshot").json()["snapshot"]
    finally:
        shutdown(booted)


def test_missing_supervisor_and_rate_load_and_name_what_is_disabled(tmp_path):
    workbook = write_workbook(tmp_path / "lean.xlsx", [ticket(1)], fields=without("Supervisor", "Rate"))

    header = header_for(workbook, tmp_path)

    assert header["row_count"] == 1
    assert header["missing_optional_columns"] == ["Rate", "Supervisor"]
    disabled = {(item["column"], item["kind"], item["feature"]): item["reason"] for item in header["disabled_features"]}
    assert ("Supervisor", "grouping", "Supervisor") in disabled
    assert ("Rate", "metric", "known_base_value_bbd") in disabled
    assert {column for column, _, _ in disabled} == {"Rate", "Supervisor"}
    for reason in disabled.values():
        assert reason.startswith("The workbook has no ")


def test_every_optional_column_has_an_explained_consequence(tmp_path):
    optional = [
        "Occupation", "Job Name", "Description of Job Work", "Modified", "ID", "Email Address",
        "Rate", "Date Approved", "Supervisor", "Modified By",
    ]
    workbook = write_workbook(tmp_path / "required-only.xlsx", [ticket(1)], fields=without(*optional))

    header = header_for(workbook, tmp_path)

    assert header["missing_optional_columns"] == optional
    assert {item["column"] for item in header["disabled_features"]} == set(optional)
    assert ("Date Approved", "metric", "observed_approval_interval_hours") in {
        (item["column"], item["kind"], item["feature"]) for item in header["disabled_features"]
    }


def test_the_committed_export_disables_nothing(app):
    header = app.get("/api/snapshot").json()["snapshot"]

    assert header["missing_optional_columns"] == []
    assert header["disabled_features"] == []
