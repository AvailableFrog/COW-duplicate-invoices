"""Check service logs for employee names, emails and descriptions from the workbook.

Used two ways: tests/conftest.py runs it over everything the API tests' service
processes printed, and CI runs it over the browser tests' service output:

    uv run python tests/log_check.py test-logs/e2e-service.log

The sensitive values are read from the committed workbook: every Employee,
Supervisor and Modified By label, every Email Address, and every description
long enough to identify a ticket (short ones such as "0", "None" or "Boxing"
would match ordinary words). Matching ignores case.
"""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

import openpyxl

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKBOOK = REPO_ROOT / "data" / "Labour Tickets Export.xlsx"
PEOPLE = ("Employee", "Supervisor", "Modified By")
MIN_NAME = 5
MIN_DESCRIPTION = 15


@lru_cache(maxsize=1)
def sensitive_values(workbook: Path = WORKBOOK) -> frozenset[str]:
    book = openpyxl.load_workbook(workbook, read_only=True, data_only=True)
    try:
        sheet = book.worksheets[0]
        rows = sheet.iter_rows(values_only=True)
        header = [str(cell) if cell is not None else "" for cell in next(rows)]
        columns = {name: header.index(name) for name in (*PEOPLE, "Email Address", "Description of Job Work") if name in header}
        values: set[str] = set()
        for row in rows:
            for name in PEOPLE:
                text = _text(row, columns.get(name))
                # A full name, or a run-together one such as "Mariocollymore"; never a short single word.
                if (len(text) >= MIN_NAME and " " in text) or len(text) >= MIN_NAME + 5:
                    values.add(text)
            email = _text(row, columns.get("Email Address"))
            if len(email) >= MIN_NAME:
                values.add(email)
            description = _text(row, columns.get("Description of Job Work"))
            if len(description) >= MIN_DESCRIPTION:
                values.add(description)
        return frozenset(value.casefold() for value in values)
    finally:
        book.close()


def _text(row: tuple, index: int | None) -> str:
    if index is None or index >= len(row) or row[index] is None:
        return ""
    return " ".join(str(row[index]).split())


def leaks(text: str, values: frozenset[str] | None = None) -> list[str]:
    """The sensitive values that appear in `text`, with whitespace collapsed and case ignored."""
    haystack = " ".join(text.split()).casefold()
    return sorted(value for value in (values if values is not None else sensitive_values()) if value in haystack)


def main(paths: list[str]) -> int:
    found = 0
    for path in paths:
        text = Path(path).read_text(encoding="utf-8", errors="replace") if Path(path).exists() else ""
        hits = leaks(text)
        lines = len(text.splitlines())
        if hits:
            found += len(hits)
            print(f"{path}: {len(hits)} sensitive value(s) in {lines} lines, e.g. {len(hits[0])}-character value")
        else:
            print(f"{path}: no employee names, emails or descriptions in {lines} lines")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
