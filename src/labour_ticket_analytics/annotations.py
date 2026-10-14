"""Annotations: the evidence report's notes on its 29 example Tickets, keyed by ticket number.

`annotations.json` was extracted from docs/source/labour-ticket-report-readable.md.
Each ticket number names its A-N example; each example carries its title,
pattern, summary, the requester's condensed review note (null where the report
gives none), its pattern's questions for Oliver and the report section it comes
from. Notes are quoted verbatim except where `review_note_reworded` is true:
C and D were reworded so no screen shows a banned phrase such as "paid twice"
(decision-log entry 29); the original wording stays in the named section. Ticket numbers survive a
re-export where Excel rows may not, so attachment is by ticket number only;
the report's Excel row is kept for reference and never used to attach.

Annotations are shown on evidence and nothing else: no matching rule reads
them, so they can never create or shape a Possible Duplicate.
"""

from __future__ import annotations

import json
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ANNOTATIONS_FILE = Path(__file__).with_name("annotations.json")


@dataclass(frozen=True)
class Annotations:
    source: str
    description: str
    tickets: dict[str, dict[str, Any]]
    examples: dict[str, dict[str, Any]]

    @classmethod
    def load(cls, path: Path = ANNOTATIONS_FILE) -> Annotations:
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(data["source"], data["description"], data["tickets"], data["examples"])

    def example(self, letter: str, excel_rows: dict[str, int], members: Collection[str] = ()) -> dict[str, Any]:
        """One example with its Tickets.

        `excel_rows` maps ticket numbers to their rows in the Snapshot shown (a
        missing number gives a null row); `members` are the ticket numbers in
        the Possible Duplicate being shown, if any.
        """
        return {
            "letter": letter,
            **self.examples[letter],
            "tickets": [
                {
                    "ticket_number": number,
                    "excel_row": excel_rows.get(number),
                    "report_excel_row": entry["report_excel_row"],
                    "in_possible_duplicate": number in members,
                }
                for number, entry in self.tickets.items()
                if entry["example"] == letter
            ],
        }

    def for_members(self, members: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The examples naming any member's ticket number, in letter order; none when no member is annotated."""
        rows = {member["ticket_number"]: member["excel_row"] for member in members if member["ticket_number"]}
        letters = sorted({self.tickets[number]["example"] for number in rows if number in self.tickets})
        return [self.example(letter, rows, set(rows)) for letter in letters]

    def payload(self, excel_rows: dict[str, int]) -> dict[str, Any]:
        """Every example and its Tickets, with each ticket number's Excel row in the Snapshot (null if absent)."""
        return {
            "source": self.source,
            "description": self.description,
            "examples": [self.example(letter, excel_rows) for letter in sorted(self.examples)],
        }


ANNOTATIONS = Annotations.load()
