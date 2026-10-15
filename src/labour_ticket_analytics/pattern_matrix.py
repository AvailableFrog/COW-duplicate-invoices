"""Review priorities by pattern: the pattern-by-source-state count matrix and the multi-label pattern filter.

Every count here is a union, never a partition (decision-log entry 64). A
Ticket counts under a pattern when a Candidate carrying that pattern links it
and it is inside the global filters; a possible duplicate counts under a
pattern when it holds such a Ticket. Tickets listed only for comparison
context are never counted, so the matrix agrees with the header tiles.

Each Ticket has exactly one source state (SOURCE_STATES), so a pattern's row
splits its Tickets without overlap; but one Ticket or possible duplicate can
carry several patterns, so the rows overlap and only the Any pattern row,
counted once per Ticket, reconciles with the registry's candidate_ticket_count.

The pattern filter is multi-label: it selects a possible duplicate when any
member matches, that is, is inside the global filters, in a selected source
state (any, when none is selected) and linked by a Candidate of a selected
pattern (any, when none is selected). Every member stays listed, marked
`in_selection` or not, and the totals count distinct possible duplicates and
distinct Tickets (Excel rows) over the union of the selected patterns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from labour_ticket_analytics import rules
from labour_ticket_analytics.filters import FilterError


@dataclass(frozen=True)
class SourceState:
    """One column of the matrix: a Ticket's recorded state, never a payment state."""

    id: str
    label: str
    definition: str

    def payload(self) -> dict[str, str]:
        return {"id": self.id, "label": self.label, "definition": self.definition}


APPROVED_KEYED = SourceState("approved_keyed", "Approved, Keyed", "Approved and Keyed, and not a flagged duplicate.")
APPROVED_NOT_KEYED = SourceState(
    "approved_not_keyed", "Approved, not Keyed", "Approved and not Keyed, and not a flagged duplicate.",
)
PENDING = SourceState("pending", "Pending", "Approval Status Pending, Keyed or not.")
REJECTED = SourceState("rejected", "Rejected", "Approval Status Rejected, Keyed or not.")
FLAGGED_DUPLICATE = SourceState(
    "flagged_duplicate", "Flagged duplicate",
    "Approved with Job Number 0, Keyed or not: staff flagged the ticket as a duplicate.",
)
UNREADABLE = SourceState(
    "unreadable", "Status or Keyed unreadable",
    "An Approval Status other than Approved, Pending or Rejected, or an Approved ticket whose Keyed is not true or"
    " false.",
)
# In display order; every Ticket falls in exactly one.
SOURCE_STATES = (APPROVED_KEYED, APPROVED_NOT_KEYED, PENDING, REJECTED, FLAGGED_DUPLICATE, UNREADABLE)

CAPTION = (
    "Tickets by pattern and source state. Pattern counts overlap: one ticket can be linked under more than one"
    " pattern, so the pattern rows do not add up to the Any pattern row."
)
MATRIX_NOTE = (
    "Each cell counts the distinct tickets inside the filters, in that source state, that a link of that pattern"
    " joins; tickets listed only for comparison are not counted. Each ticket has one source state, so a row's cells"
    " add up to its tickets, but a ticket or possible duplicate can carry several patterns, so the rows do not add up"
    " to the Any pattern row. Nothing here splits tickets into duplicates and not duplicates."
)
FILTER_NOTE = (
    "Selecting several patterns lists the possible duplicates matching any of them. Pattern counts overlap: a"
    " possible duplicate or ticket can carry more than one pattern, so the totals count each once and are at most the"
    " sum of the patterns' own counts."
)

_PATTERN_IDS = [pattern.id for pattern in rules.PATTERNS]
_STATE_IDS = [state.id for state in SOURCE_STATES]


def source_state(member: dict[str, Any]) -> SourceState:
    """A Ticket's one source state; a flagged duplicate is only that, whatever its Keyed."""
    if member["flagged_duplicate"]:
        return FLAGGED_DUPLICATE
    status, keyed = member["status"], member["keyed"]
    if status == "Approved":
        return APPROVED_KEYED if keyed is True else APPROVED_NOT_KEYED if keyed is False else UNREADABLE
    return {"Pending": PENDING, "Rejected": REJECTED}.get(status, UNREADABLE)


@dataclass(frozen=True)
class PatternFilter:
    """The patterns and source states selected on Review priorities; empty means any."""

    patterns: tuple[str, ...] = ()
    source_states: tuple[str, ...] = ()

    @classmethod
    def build(cls, *, patterns: Iterable[str] = (), source_states: Iterable[str] = ()) -> PatternFilter:
        """A validated selection in registry order; raises FilterError for an ID outside the allowlist."""
        patterns, source_states = list(patterns), list(source_states)
        for pattern in patterns:
            if pattern not in _PATTERN_IDS:
                raise FilterError("pattern", f"pattern must be one of {', '.join(_PATTERN_IDS)}, not {pattern!r}")
        for state in source_states:
            if state not in _STATE_IDS:
                raise FilterError(
                    "source_state", f"source state must be one of {', '.join(_STATE_IDS)}, not {state!r}",
                )
        return cls(
            tuple(pattern for pattern in _PATTERN_IDS if pattern in patterns),
            tuple(state for state in _STATE_IDS if state in source_states),
        )

    @property
    def active(self) -> bool:
        return bool(self.patterns or self.source_states)

    def matches(self, member: dict[str, Any], linked: set[str]) -> bool:
        """Whether a member counts: inside the global filters, in a selected state, linked by a selected pattern."""
        return (
            member["in_filter"]
            and (not self.source_states or member["source_state"] in self.source_states)
            and (not self.patterns or bool(linked.intersection(self.patterns)))
        )

    def describe(self) -> str:
        labels = {pattern.id: pattern.label for pattern in rules.PATTERNS}
        states = {state.id: state.label for state in SOURCE_STATES}
        parts = [" or ".join(labels[pattern] for pattern in self.patterns) if self.patterns else "any pattern"]
        if self.source_states:
            parts.append("tickets that are " + " or ".join(states[state] for state in self.source_states))
        return "; ".join(parts)


@dataclass(frozen=True)
class _Linked:
    """A possible duplicate with, for each member's Excel row, the patterns of the Candidates linking it."""

    item: dict[str, Any]
    patterns: dict[int, set[str]]

    def matching(self, selection: PatternFilter) -> list[int]:
        return [
            member["excel_row"] for member in self.item["members"]
            if selection.matches(member, self.patterns[member["excel_row"]])
        ]


def review_priorities(possible_duplicates: list[dict[str, Any]], selection: PatternFilter) -> dict[str, Any]:
    """The list under the pattern filter, re-ranked, with the per-pattern counts, union totals and the matrix.

    `possible_duplicates` are those with any member inside the global
    filters. The matrix is counted under the global filters alone, since it is
    what the pattern filter is chosen from.
    """
    linked = [_link(item) for item in possible_duplicates]
    selected = []
    for entry in linked:
        rows = set(entry.matching(selection))
        if rows:
            members = [{**member, "in_selection": member["excel_row"] in rows} for member in entry.item["members"]]
            selected.append({key: value for key, value in entry.item.items() if key != "rank"} | {"members": members})
    listed = rules.ranked(selected)
    counts = [
        {
            **pattern.payload(),
            **_totals(linked, PatternFilter((pattern.id,), selection.source_states)),
            "selected": pattern.id in selection.patterns,
        }
        for pattern in rules.PATTERNS
    ]
    return {
        "possible_duplicates": listed,
        "pattern_filter": {
            "patterns": list(selection.patterns),
            "source_states": list(selection.source_states),
            "active": selection.active,
            "description": selection.describe(),
            "counts": counts,
            "totals": _totals(linked, selection),
            "note": FILTER_NOTE,
        },
        "pattern_matrix": _matrix(linked),
    }


def _link(item: dict[str, Any]) -> _Linked:
    """Annotate a possible duplicate with its pattern IDs, each member's source state and the member breakdown."""
    patterns: dict[int, set[str]] = {member["excel_row"]: set() for member in item["members"]}
    for candidate in item["candidates"]:
        pattern = rules.PATTERN_BY_LABEL[candidate["pattern"]].id
        for row in candidate["excel_rows"]:
            patterns[row].add(pattern)
    members = [{**member, "source_state": source_state(member).id} for member in item["members"]]
    breakdown = [
        {"id": state.id, "label": state.label, "tickets": tickets}
        for state in SOURCE_STATES
        if (tickets := sum(1 for member in members if member["source_state"] == state.id))
    ]
    annotated = {
        **item,
        "pattern_ids": [rules.PATTERN_BY_LABEL[label].id for label in item["pattern_labels"]],
        # Every member's state, inside the filters or not: a mixed possible duplicate keeps its breakdown.
        "source_states": breakdown,
        "members": members,
    }
    return _Linked(annotated, patterns)


def _totals(linked: list[_Linked], selection: PatternFilter) -> dict[str, int]:
    """Distinct possible duplicates and distinct Tickets matching; possible duplicates are disjoint, so rows add."""
    matching = [entry.matching(selection) for entry in linked]
    return {
        "possible_duplicates": sum(1 for rows in matching if rows),
        "tickets": sum(len(rows) for rows in matching),
    }


def _matrix(linked: list[_Linked]) -> dict[str, Any]:
    def row(patterns: tuple[str, ...]) -> dict[str, Any]:
        return {
            **_totals(linked, PatternFilter(patterns)),
            "cells": [
                {"source_state": state.id, "tickets": _totals(linked, PatternFilter(patterns, (state.id,)))["tickets"]}
                for state in SOURCE_STATES
            ],
        }

    return {
        "caption": CAPTION,
        "note": MATRIX_NOTE,
        "grain": "Ticket",
        "source_states": [state.payload() for state in SOURCE_STATES],
        "rows": [{"pattern": pattern.payload(), **row((pattern.id,))} for pattern in rules.PATTERNS],
        "any_pattern": row(()),
    }
