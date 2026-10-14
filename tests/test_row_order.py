"""Ticket #2: the import keeps the original row order, blank rows included."""

from conftest import running
from synthetic import FIELDS, ticket, write_workbook


def test_a_blank_row_in_the_middle_keeps_its_excel_row_and_later_rows_keep_theirs(tmp_path):
    workbook = write_workbook(tmp_path / "gap.xlsx", [ticket(1), None, ticket(2, Employee="Ben")])

    with running(workbook, tmp_path) as booted:
        header = booted.get("/api/snapshot").json()["snapshot"]
        fingerprint = header["fingerprint"]
        gap = booted.get(f"/api/snapshots/{fingerprint}/tickets/3").json()
        ben = booted.get(f"/api/snapshots/{fingerprint}/tickets/4").json()

    assert header["row_count"] == 3
    assert header["field_count"] == len(FIELDS)
    assert gap["dataframe_index"] == 1
    assert {cell["raw_type"] for cell in gap["cells"]} == {"blank"}
    assert [(cell["field"], cell["value"]) for cell in ben["cells"][:3]] == [
        ("Employee", "Ben"), ("Occupation", "Labourer"), ("Ticket Number", "L000002"),
    ]
