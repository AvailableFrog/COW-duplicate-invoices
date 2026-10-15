"""Ticket #18: each of the ten section 12 data-correctness criteria names tests that exist.

The mapping lives once, in docs/test-report.md, where a reviewer reads it.
This test parses that table and checks every named test function is defined
in the named file, so a renamed or deleted test fails here instead of leaving
a criterion silently uncovered. That the named tests pass is the job of the
full run.
"""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs" / "test-report.md"


def criteria() -> dict[int, list[tuple[str, str]]]:
    text = REPORT.read_text(encoding="utf-8")
    section = text.split("## Section 12 data-correctness criteria", 1)[1].split("\n## ", 1)[0]
    mapping: dict[int, list[tuple[str, str]]] = {}
    for line in section.splitlines():
        row = re.match(r"^\| (\d+) \|", line)
        if row:
            mapping[int(row.group(1))] = re.findall(r"`(test_\w+\.py)::(test_\w+)`", line)
    return mapping


def defined_tests(filename: str) -> set[str]:
    tree = ast.parse((ROOT / "tests" / filename).read_text(encoding="utf-8"))
    return {node.name for node in tree.body if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")}


def test_all_ten_criteria_are_mapped_to_at_least_one_test():
    mapping = criteria()
    assert sorted(mapping) == list(range(1, 11))
    assert all(mapping[number] for number in mapping)


def test_every_mapped_test_exists_in_its_file():
    missing = [
        (number, filename, name)
        for number, tests in criteria().items()
        for filename, name in tests
        if name not in defined_tests(filename)
    ]
    assert missing == []
