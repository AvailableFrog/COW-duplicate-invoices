"""The evidence behind one Possible Duplicate, as the evidence drawer shows it.

A Possible Duplicate is addressed by any of its member Tickets (Snapshot and
Excel row), never by its display identifier, which is derived from ticket
numbers and is not a storage key (ADR 0004). The payload keeps every source
cell exactly as imported: values are never trimmed, joined or rendered, so
blank, zero and false stay distinguishable and whitespace survives.

The members' source states are broken down ticket by ticket; nothing here
summarises them as paid or unpaid, which the export cannot show.
"""

from __future__ import annotations

from typing import Any

from labour_ticket_analytics.annotations import Annotations
from labour_ticket_analytics.rules import RULES
from labour_ticket_analytics.timeparse import TimeParse, compare

# The claim timeline's columns, after the ticket itself.
TIMELINE_FIELDS = ("Date", "Created", "Modified", "Date Approved", "Supervisor")


def evidence(
    possible_duplicate: dict[str, Any],
    tickets: list[dict[str, Any]],
    parses: dict[int, TimeParse],
    annotations: Annotations,
) -> dict[str, Any]:
    """The drawer payload for one Possible Duplicate.

    `possible_duplicate` is the composed item the Review priorities list shows,
    `tickets` its members' fetched Tickets in member order, and `parses` their
    Time parse results by Excel row.
    """
    shown = _shown(possible_duplicate["members"], tickets, parses, annotations)
    return {
        "display_id": possible_duplicate["display_id"],
        "tier": possible_duplicate["tier"],
        "exact_repeat_not_flagged": possible_duplicate["exact_repeat_not_flagged"],
        "rule_ids": possible_duplicate["rule_ids"],
        "pattern_labels": possible_duplicate["pattern_labels"],
        "reason": possible_duplicate["summary"],
        "candidates": [_candidate(candidate, parses) for candidate in possible_duplicate["candidates"]],
        "status_breakdown": _status_breakdown(shown["members"]),
        **shown,
    }


def pair_explanation(
    explanation: dict[str, Any],
    members: list[dict[str, Any]],
    tickets: list[dict[str, Any]],
    parses: dict[int, TimeParse],
    display_ids: dict[int, str],
    annotations: Annotations,
) -> dict[str, Any]:
    """Why two Tickets are or are not linked, with the same evidence the drawer shows for a possible duplicate.

    `explanation` is the rules' verdicts and summary, `members` and `tickets`
    the two Tickets in Excel-row order, and `display_ids` the possible
    duplicate each Ticket is in, if any. Nothing here says one Ticket repeats
    or outranks the other unless a rule linked them.
    """
    first, second = (member["excel_row"] for member in members)
    shown = _shown(
        [{**member, "possible_duplicate": display_ids.get(member["excel_row"])} for member in members],
        tickets, parses, annotations,
    )
    together = display_ids.get(first)
    return {
        "excel_rows": [first, second],
        **explanation,
        "time_comparison": compare(parses[first], parses[second]),
        "possible_duplicate": together if together is not None and together == display_ids.get(second) else None,
        **shown,
    }


def _shown(
    members: list[dict[str, Any]], tickets: list[dict[str, Any]], parses: dict[int, TimeParse], annotations: Annotations
) -> dict[str, Any]:
    """The evidence shown for any set of Tickets: members with provenance and Time, timeline, source table, Annotations."""
    members = [
        {
            **member,
            "provenance": {
                "snapshot_fingerprint": ticket["snapshot_fingerprint"],
                "sheet": ticket["sheet"],
                "excel_row": ticket["excel_row"],
                "dataframe_index": ticket["dataframe_index"],
            },
            "issues": ticket["issues"],
            "time_parse": parses[member["excel_row"]].payload(),
        }
        for member, ticket in zip(members, tickets)
    ]
    fields = _transposed(tickets)
    return {
        "members": members,
        "timeline": _timeline(members, tickets),
        "fields": fields,
        "differing_fields": [row["field"] for row in fields if row["differs"]],
        "annotations": annotations.for_members(members),
    }


def _candidate(candidate: dict[str, Any], parses: dict[int, TimeParse]) -> dict[str, Any]:
    """A Candidate edge with its rule's name and how the two Tickets' work periods compare."""
    first, second = candidate["excel_rows"]
    return {
        **candidate,
        "rule_label": RULES[candidate["rule_id"]].label,
        "time_comparison": compare(parses[first], parses[second]),
    }


def _status_breakdown(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """How many members are in each source state: status, Keyed and the flag, never a payment state."""
    counts: dict[tuple[Any, ...], int] = {}
    for member in members:
        key = (member["status"], member["keyed"], member["flagged_duplicate"])
        counts[key] = counts.get(key, 0) + 1
    return [
        {
            "status": status,
            "keyed": keyed,
            "flagged_duplicate": flagged,
            "label": _state_label(status, keyed, flagged),
            "tickets": tickets,
        }
        for (status, keyed, flagged), tickets in counts.items()
    ]


def _state_label(status: str | None, keyed: bool | None, flagged: bool) -> str:
    keyed_text = "Keyed unknown" if keyed is None else "Keyed" if keyed else "not Keyed"
    label = f"{status or 'Unknown status'}, {keyed_text}"
    return f"{label}, flagged duplicate" if flagged else label


def _timeline(members: list[dict[str, Any]], tickets: list[dict[str, Any]]) -> dict[str, Any]:
    """The members in Created order, oldest first; a Ticket without a usable Created comes last, by Excel row."""
    order = sorted(
        zip(members, tickets),
        key=lambda pair: (pair[0]["created"] is None, pair[0]["created"] or "", pair[0]["excel_row"]),
    )
    entries = []
    for member, ticket in order:
        cells = {cell["field"]: cell for cell in ticket["cells"]}
        entries.append({
            "excel_row": member["excel_row"],
            "ticket_number": member["ticket_number"],
            "cells": [_cell(cells[name]) if name in cells else None for name in TIMELINE_FIELDS],
        })
    return {"fields": list(TIMELINE_FIELDS), "entries": entries}


def _transposed(tickets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per source field, one cell per member, with whether the members' values differ."""
    by_field = [{cell["field"]: cell for cell in ticket["cells"]} for ticket in tickets]
    rows = []
    for cell in tickets[0]["cells"]:
        cells = [
            {"excel_row": ticket["excel_row"], **_cell(cells[cell["field"]])}
            for ticket, cells in zip(tickets, by_field)
        ]
        rows.append({
            "field": cell["field"],
            "position": cell["position"],
            "differs": len({_comparable(item) for item in cells}) > 1,
            "cells": cells,
        })
    return rows


def _cell(cell: dict[str, Any]) -> dict[str, Any]:
    return {"raw_type": cell["raw_type"], "value": cell["value"], "number_format": cell["number_format"]}


def _comparable(cell: dict[str, Any]) -> tuple[str, Any]:
    """A cell's value together with its kind, so 0, false, blank and the text "0" never compare equal.

    Integers and floats are one kind, so 8 and 8.0 are the same number. Text
    is compared exactly as written, so a spacing difference is a difference.
    """
    kind = "number" if cell["raw_type"] in ("int", "float") else cell["raw_type"]
    return kind, cell["value"]
