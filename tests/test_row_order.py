"""Ticket #2: the import keeps the original row order, blank rows included."""

import openpyxl

from conftest import boot, shutdown

FIELDS = ["Employee", "Ticket Number", "Keyed"]


def write_workbook(path, rows):
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Labour Tickets (1)"
    sheet.append(FIELDS)
    for row in rows:
        sheet.append(row)
    book.save(path)


def test_a_blank_row_in_the_middle_keeps_its_excel_row_and_later_rows_keep_theirs(tmp_path):
    workbook = tmp_path / "gap.xlsx"
    write_workbook(workbook, [["Ann", "L1", True], [None, None, None], ["Ben", "L2", False]])

    booted = boot(workbook, tmp_path)
    try:
        header = booted.get("/api/snapshot").json()["snapshot"]
        fingerprint = header["fingerprint"]
        gap = booted.get(f"/api/snapshots/{fingerprint}/tickets/3").json()
        ben = booted.get(f"/api/snapshots/{fingerprint}/tickets/4").json()
    finally:
        shutdown(booted)

    assert header["row_count"] == 3
    assert header["field_count"] == 3
    assert gap["dataframe_index"] == 1
    assert [cell["raw_type"] for cell in gap["cells"]] == ["blank", "blank", "blank"]
    assert [cell["value"] for cell in ben["cells"]] == ["Ben", "L2", False]
