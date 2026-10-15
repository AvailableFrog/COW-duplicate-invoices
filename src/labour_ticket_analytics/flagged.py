"""The Flagged duplicates view: every flagged duplicate, its counterparts, and whether a reviewer settled one.

A flagged duplicate is a Ticket staff approved with Job Number 0
(metrics.FLAGGED_DUPLICATE_SCOPE). The view lists the same Tickets the
Flagged duplicates tile counts, under the same filters, and says for each
whether the Flagged-duplicate counterpart rule found a counterpart or the
relationship is unresolved. That split is shown beside the tile, never folded
into its count.

Every counterpart the rule found is listed, uncertain ones marked; none is
chosen as the original. A counterpart is settled only when a reviewer settled
that pair (rules.settled_rows); until then the possible duplicate holding the
flagged duplicate stays in the third review-priority tier.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from labour_ticket_analytics import rules


@dataclass(frozen=True)
class CounterpartStatus:
    id: str
    label: str
    definition: str

    def payload(self) -> dict[str, str]:
        return {"id": self.id, "label": self.label, "definition": self.definition}


COUNTERPART_FOUND = CounterpartStatus(
    "counterpart_found", "Counterpart found",
    "The Flagged-duplicate counterpart rule links this ticket to at least one other ticket for the same employee and"
    " date. Every plausible counterpart is listed, uncertain ones marked; none is chosen as the original, and the"
    " relationship stays open until a reviewer settles it.",
)
UNRESOLVED = CounterpartStatus(
    "unresolved", "Unresolved",
    "No counterpart found: no ticket for the same employee and date has the same four hour and pay amounts, the same"
    " work periods, or the same unresolved Time text and description. Other rules may still link it.",
)
COUNTERPART_STATUSES = (COUNTERPART_FOUND, UNRESOLVED)

NOTE = (
    "Each flagged duplicate the Flagged duplicates tile counts, with whether a counterpart was found. The split is"
    " shown here, separately from the tile: the tile counts what staff flagged, and asserts nothing about whether"
    " the analysis agrees. A counterpart is a possible link, not the retained claim, until a reviewer settles it"
    " with Confirmed duplicate, Replacement ticket or a kept/replaced link."
)


def view(
    flagged: Iterable[dict[str, Any]],
    candidates: list[rules.Candidate],
    members: dict[int, dict[str, Any]],
    settled_pairs: set[tuple[int, int]],
) -> list[dict[str, Any]]:
    """One entry per flagged duplicate inside the filters, lowest ticket number first.

    `flagged` are the flagged duplicates with their source state, `candidates`
    the Snapshot's Candidates, `members` every Ticket in a Candidate, and
    `settled_pairs` the pairs a reviewer settled.
    """
    components = rules.compose(candidates)
    holding: dict[int, dict[str, Any]] = {}
    for component in components:
        item = rules.possible_duplicate(component, members, settled_pairs)
        for member in item["members"]:
            holding[member["excel_row"]] = {"display_id": item["display_id"], "tier": item["tier"]}
    settled = rules.settled_rows(candidates, settled_pairs)
    links: dict[int, list[rules.Candidate]] = {}
    for candidate in candidates:
        if candidate.rule_id == rules.FLAGGED_DUPLICATE_COUNTERPART.id:
            for row in (candidate.first_row, candidate.second_row):
                links.setdefault(row, []).append(candidate)
    entries = []
    for ticket in sorted((ticket for ticket in flagged if ticket["in_filter"]), key=rules.ticket_order):
        row = ticket["excel_row"]
        counterparts = [
            _counterpart(candidate, members, settled_pairs, row)
            for candidate in sorted(links.get(row, []), key=lambda c: c.first_row + c.second_row - row)
        ]
        status = COUNTERPART_FOUND if counterparts else UNRESOLVED
        entries.append({
            **ticket,
            "counterpart_status": {"id": status.id, "label": status.label},
            "counterparts": counterparts,
            "settled_by_review": row in settled,
            "possible_duplicate": holding.get(row),
        })
    return entries


def counts(entries: list[dict[str, Any]]) -> dict[str, int]:
    found = sum(1 for entry in entries if entry["counterparts"])
    return {"flagged_duplicates": len(entries), "counterpart_found": found, "unresolved": len(entries) - found}


def _counterpart(
    candidate: rules.Candidate, members: dict[int, dict[str, Any]], settled_pairs: set[tuple[int, int]], row: int,
) -> dict[str, Any]:
    other = candidate.second_row if candidate.first_row == row else candidate.first_row
    return {
        **members[other],
        "excel_rows": [candidate.first_row, candidate.second_row],
        "certain": candidate.evidence_strength != rules.UNCERTAIN_COUNTERPART_STRENGTH,
        "reason": candidate.reason,
        "settles": (candidate.first_row, candidate.second_row) in settled_pairs,
    }
