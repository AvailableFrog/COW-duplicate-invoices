"""Synthetic same-schema workbooks of any size, for scale and rule-coverage tests (ticket #37).

Every value is visibly synthetic: employees are "Synthetic Worker NNNNN", emails
end in "@synthetic.invalid", descriptions read "Synthetic task ...", and ticket
numbers start with "S". Nothing here describes a real person.

The workbook has two parts:

- Background tickets, one per (employee, date), so no two can ever meet in a
  matching rule's search space. They still carry the shapes the views must
  handle: Pending and Rejected tickets, Approved but not Keyed, missing rates,
  times without AM/PM, and a few work dates outside the reporting window.
- Planted cases: for each matching rule, one pair of tickets under its own
  synthetic employee that the rule must link. `PLANTED` records which rule each
  pair is for, by Excel row, so a test can check the rule found exactly them.

The same seed always gives the same workbook.

    uv run python tests/generate.py --rows 50000 --seed 1 /tmp/scale.xlsx
"""

from __future__ import annotations

import argparse
import datetime as dt
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from synthetic import FIELDS, SHEET  # noqa: E402

FIRST_DAY = dt.datetime(2026, 9, 1)
DAYS = 36
JOBS = [(40000 + index, f"Synthetic site {index:03d}") for index in range(1, 201)]
SUPERVISORS = [f"Synthetic Supervisor {letter}" for letter in "ABCDEFGHJK"]
CONFIDENT_TIMES = ["7:30 am to 4:30 pm", "7:00 am to 3:30 pm", "8:00 am to 5:00 pm", "7:30 am to 12:30 pm"]
AMBIGUOUS_TIMES = ["7:30-4:30", "730-1130", "8-5"]


@dataclass(frozen=True)
class Planted:
    rule_id: str
    first_row: int
    second_row: int


def _base(number: int, employee: str, day: dt.datetime, rng: random.Random) -> dict[str, Any]:
    job_number, job_name = rng.choice(JOBS)
    created = day + dt.timedelta(days=rng.randint(1, 5), hours=rng.randint(6, 20), minutes=rng.choice([0, 15, 30, 45]))
    return {
        "Employee": employee,
        "Occupation": rng.choice(["Labourer", "Checker", "Chainman", "Carpenter A Class"]),
        "Ticket Number": f"S{number:07d}",
        "Job Name": job_name,
        "Job Number": job_number,
        "Date": day,
        "Time": rng.choice(CONFIDENT_TIMES),
        "Regular Hours": 8,
        "Overtime": rng.choice([0, 0, 0, 1]),
        "Double Time": 0,
        "Job Work Pay": 0,
        "Description of Job Work": f"Synthetic task {rng.randint(1, 400)}",
        "Supervisor": rng.choice(SUPERVISORS),
        "Approval Status": "Approved",
        "Modified": created + dt.timedelta(days=2),
        "Created": created,
        "ID": 900000 + number,
        "Email Address": f"{employee.lower().replace(' ', '.')}@synthetic.invalid",
        "Keyed": True,
        "Rate": rng.choice([14.53, 17.05, 19.08, 19.47]),
        "Date Approved": created + dt.timedelta(days=1, hours=2),
        "Modified By": "Synthetic Reviewer",
    }


def _background(number: int, index: int, workers: int, rng: random.Random) -> dict[str, Any]:
    # Worker and day both come from the index, so (employee, date) never repeats.
    worker, day_offset = index % workers, index // workers
    values = _base(number, f"Synthetic Worker {worker:05d}", FIRST_DAY + dt.timedelta(days=day_offset), rng)
    roll = rng.random()
    if roll < 0.04:
        values.update({"Approval Status": "Pending", "Keyed": False, "Date Approved": None, "Rate": None})
    elif roll < 0.08:
        values.update({"Approval Status": "Rejected", "Keyed": False})
    elif roll < 0.13:
        values["Keyed"] = False
    if rng.random() < 0.10:
        values["Time"] = rng.choice(AMBIGUOUS_TIMES)
    if rng.random() < 0.0005:
        values["Date"] = dt.datetime(2050, 9, 1) + dt.timedelta(days=day_offset)
    return values


def _planted(start: int, rng: random.Random) -> tuple[list[dict[str, Any]], list[tuple[str, int, int]]]:
    """One pair per rule, each under its own employee; returns the tickets and (rule, offset, offset) pairs."""
    day = FIRST_DAY + dt.timedelta(days=3)
    tickets: list[dict[str, Any]] = []
    pairs: list[tuple[str, int, int]] = []

    def pair(rule_id: str, employee: str, first: dict[str, Any], second: dict[str, Any]) -> None:
        a = _base(start + len(tickets), employee, day, rng) | {"Job Number": 41001, "Job Name": "Synthetic site planted"}
        a.update(first)
        tickets.append(a)
        b = dict(a, **{"Ticket Number": f"S{start + len(tickets):07d}", "ID": 900000 + start + len(tickets)})
        b["Created"] = a["Created"] + dt.timedelta(days=1)
        b.update(second)
        tickets.append(b)
        pairs.append((rule_id, len(tickets) - 2, len(tickets) - 1))

    pair("strict_repeat", "Synthetic Planted Strict", {"Time": "7:30 am to 4:30 pm"}, {})
    pair("time_text_variant", "Synthetic Planted Spacing", {"Time": "730am 430 pm"}, {"Time": "730 am 430 pm"})
    pair("name_space_variant", "Synthetic Planted Name", {}, {"Employee": "SyntheticPlantedName"})
    pair(
        "work_period_conflict", "Synthetic Planted Overlap",
        {"Time": "7:30 am to 12:30 pm", "Regular Hours": 5},
        {"Time": "10:00 am to 2:00 pm", "Regular Hours": 4, "Job Number": 41002, "Job Name": "Synthetic site other"},
    )
    pair("ambiguous_period_comparison", "Synthetic Planted Ambiguous", {"Time": "7:30-11:30", "Regular Hours": 4}, {"Time": "8:30-12:30"})
    pair(
        "flagged_duplicate_counterpart", "Synthetic Planted Flagged",
        {"Time": "7:30 am to 4:30 pm"}, {"Job Number": 0, "Time": "7:00 am to 3:30 pm"},
    )
    pair(
        "repeated_component", "Synthetic Planted Component",
        {"Job Work Pay": 50, "Time": "7:30 am to 9:30 am", "Regular Hours": 2},
        {"Job Work Pay": 50, "Time": "1:00 pm to 4:00 pm", "Regular Hours": 3},
    )
    return tickets, pairs


def generate(rows: int, seed: int = 1) -> tuple[list[dict[str, Any]], list[Planted]]:
    """`rows` Tickets in workbook order and the planted pairs by Excel row (row 2 is the first Ticket)."""
    rng = random.Random(seed)
    planted_rng = random.Random(seed + 1)
    planted_count = 14
    if rows < planted_count:
        raise ValueError(f"need at least {planted_count} rows for the planted cases")
    background_count = rows - planted_count
    workers = max(1, -(-background_count // DAYS))
    background = [_background(index + 1, index, workers, rng) for index in range(background_count)]
    planted_tickets, pairs = _planted(background_count + 1, planted_rng)
    tickets = background + planted_tickets
    offset = len(background) + 2
    return tickets, [Planted(rule, offset + first, offset + second) for rule, first, second in pairs]


def write_large(path: Path, tickets: list[dict[str, Any]]) -> Path:
    """Write the workbook in streaming mode, fast enough for 50,000 rows."""
    book = openpyxl.Workbook(write_only=True)
    sheet = book.create_sheet(SHEET)
    sheet.append(FIELDS)
    for values in tickets:
        sheet.append([values.get(name) for name in FIELDS])
    book.save(path)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("path", type=Path)
    parser.add_argument("--rows", type=int, default=50_000)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args(argv)
    tickets, planted = generate(args.rows, args.seed)
    write_large(args.path, tickets)
    print(f"wrote {len(tickets)} tickets to {args.path}; planted: " + ", ".join(f"{p.rule_id} {p.first_row}/{p.second_row}" for p in planted))
    return 0


if __name__ == "__main__":
    sys.exit(main())
