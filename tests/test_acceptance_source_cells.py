"""Ticket #18: every source cell of the evidence report's 14 comparisons, through the API.

The expected values are not copied into this file. They are parsed from the
"Exact source rows" tables of docs/source/labour-ticket-report-readable.md,
where each cell is JSON: quoted strings keep their spaces, `\\n` is a line
break, `null` is a blank, and date cells are ISO strings ("2026-09-28 00:00:00").
29 example Tickets x 22 fields = 638 cells.

Every example row that belongs to a possible duplicate is read through the
possible-duplicate detail API, the payload behind the evidence drawer: 24 of
the 29. Five belong to none: A's two (separate work on different jobs), N's
two (its dates sit only in the description) and L's row 2152. For those the
detail API answers "not found" and the cells are read through the
single-Ticket API. L's other row, 2151, is in a possible duplicate with M's
row 2149, whose times overlap it, but never with 2152.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from conftest import HANDOFF_WORKBOOK_SHA256

REPORT = Path(__file__).resolve().parents[1] / "docs" / "source" / "labour-ticket-report-readable.md"
BASE = f"/api/snapshots/{HANDOFF_WORKBOOK_SHA256}/tickets"
FIELD_COUNT = 22
NOT_LINKED = {"A", "L", "N"}
ISO_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


@dataclass(frozen=True)
class Comparison:
    letter: str
    excel_rows: tuple[int, ...]
    cells: dict[int, dict[str, object]]  # excel row -> field -> JSON value from the report


def parse_report() -> list[Comparison]:
    comparisons: list[Comparison] = []
    letter = None
    lines = REPORT.read_text(encoding="utf-8").splitlines()
    i = 0
    while i < len(lines):
        heading = re.match(r"^### ([A-N])\. ", lines[i])
        if heading:
            letter = heading.group(1)
        if lines[i].startswith("<summary>Exact source rows:"):
            while not lines[i].startswith("| Source field"):
                i += 1
            excel_rows = tuple(int(n) for n in re.findall(r"Excel (\d+)", lines[i]))
            i += 2  # header and separator
            cells: dict[int, dict[str, object]] = {row: {} for row in excel_rows}
            while lines[i].startswith("|"):
                field = lines[i].split("|")[1].strip().strip("*").removesuffix(" (different)")
                values = re.findall(r"`([^`]*)`", lines[i])
                assert len(values) == len(excel_rows), lines[i]
                for row, value in zip(excel_rows, values):
                    cells[row][field] = json.loads(value)
                i += 1
            assert letter is not None
            comparisons.append(Comparison(letter, excel_rows, cells))
        i += 1
    return comparisons


COMPARISONS = parse_report()


def expected_cell(report_value: object, raw_type: str) -> tuple[str, object]:
    """The (raw type, value) the API must return for one report cell."""
    if report_value is None:
        return ("blank", None)
    if isinstance(report_value, bool):
        return ("bool", report_value)
    if isinstance(report_value, int):
        return ("int", report_value)
    if isinstance(report_value, float):
        return ("float", report_value)
    assert isinstance(report_value, str)
    if raw_type == "datetime" and ISO_DATETIME.match(report_value):
        return ("datetime", report_value.replace(" ", "T"))
    return ("str", report_value)


def read_columns(app, comparison: Comparison) -> tuple[dict[int, dict[str, tuple[str, object]]], dict[int, str | None]]:
    """Each example row's cells and the display ID of the possible duplicate holding it.

    A row in any possible duplicate is read through the detail API; a row in
    none (the API answers 404) is read through the single-Ticket API.
    """
    columns: dict[int, dict[str, tuple[str, object]]] = {}
    display_ids: dict[int, str | None] = {}
    for row in comparison.excel_rows:
        response = app.get(f"{BASE}/{row}/possible-duplicate")
        if response.status_code == 200:
            payload = response.json()
            display_ids[row] = payload["display_id"]
            index = [member["excel_row"] for member in payload["members"]].index(row)
            columns[row] = {f["field"]: (f["cells"][index]["raw_type"], f["cells"][index]["value"]) for f in payload["fields"]}
        else:
            assert response.status_code == 404, response.text
            display_ids[row] = None
            ticket = app.get(f"{BASE}/{row}")
            assert ticket.status_code == 200, ticket.text
            columns[row] = {c["field"]: (c["raw_type"], c["value"]) for c in ticket.json()["cells"]}
    return columns, display_ids


def test_the_report_holds_14_comparisons_of_29_tickets_and_638_cells():
    letters = [c.letter for c in COMPARISONS]
    assert sorted(letters) == list("ABCDEFGHIJKLMN")
    rows = [row for c in COMPARISONS for row in c.excel_rows]
    assert len(rows) == len(set(rows)) == 29
    assert sum(len(fields) for c in COMPARISONS for fields in c.cells.values()) == 29 * FIELD_COUNT == 638


@pytest.mark.parametrize("comparison", COMPARISONS, ids=[c.letter for c in COMPARISONS])
def test_every_source_cell_of_the_comparison_is_returned_exactly_as_the_report_prints_it(app, comparison):
    columns, _ = read_columns(app, comparison)

    mismatches = []
    for row in comparison.excel_rows:
        assert set(columns[row]) == set(comparison.cells[row]), (comparison.letter, row)
        assert len(columns[row]) == FIELD_COUNT
        for field, report_value in comparison.cells[row].items():
            raw_type, value = columns[row][field]
            if (raw_type, value) != expected_cell(report_value, raw_type):
                mismatches.append((row, field, report_value, raw_type, value))
    assert mismatches == []


def test_all_638_cells_are_checked_and_every_linked_example_opens_through_the_detail_api(app):
    checked = 0
    through_detail = 0
    for comparison in COMPARISONS:
        columns, display_ids = read_columns(app, comparison)
        through_detail += sum(1 for row in comparison.excel_rows if display_ids[row] is not None)
        for row in comparison.excel_rows:
            for field, report_value in comparison.cells[row].items():
                raw_type, value = columns[row][field]
                assert (raw_type, value) == expected_cell(report_value, raw_type)
                checked += 1
    assert checked == 638
    # Every example row but five belongs to some possible duplicate: A's two, N's two and L's 2152.
    assert through_detail == 24


def test_each_linked_example_is_one_possible_duplicate_and_a_l_n_are_never_grouped(app):
    for comparison in COMPARISONS:
        _, display_ids = read_columns(app, comparison)
        holders = set(display_ids.values())
        if comparison.letter in NOT_LINKED:
            # Separate work (A, L) or dates only in the description (N): never grouped together.
            assert len(holders) > 1 or holders == {None}, (comparison.letter, display_ids)
        else:
            assert len(holders) == 1 and None not in holders, (comparison.letter, display_ids)


def test_f_and_h_are_separate_possible_duplicates_though_both_are_mario_collymore(app):
    by_letter = {c.letter: c for c in COMPARISONS}
    f_columns, f_ids = read_columns(app, by_letter["F"])
    h_columns, h_ids = read_columns(app, by_letter["H"])

    f_holders, h_holders = set(f_ids.values()), set(h_ids.values())
    assert len(f_holders) == len(h_holders) == 1 and None not in f_holders | h_holders
    assert f_holders.isdisjoint(h_holders)
    assert set(by_letter["F"].excel_rows).isdisjoint(by_letter["H"].excel_rows)
    assert {f_columns[r]["Date"][1] for r in by_letter["F"].excel_rows} == {"2026-09-10T00:00:00"}
    assert {h_columns[r]["Date"][1] for r in by_letter["H"].excel_rows} == {"2026-09-23T00:00:00"}
    assert {h_columns[r]["Employee"][1] for r in by_letter["H"].excel_rows} == {"Mario Collymore", "Mariocollymore"}


def test_gs_whitespace_difference_in_time_survives_verbatim(app):
    g = next(c for c in COMPARISONS if c.letter == "G")
    columns, display_ids = read_columns(app, g)
    assert None not in display_ids.values()
    assert columns[82]["Time"] == ("str", "730am 430 pm")
    assert columns[103]["Time"] == ("str", "730 am 430 pm")
