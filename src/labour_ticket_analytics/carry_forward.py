"""Carrying review decisions forward to a new Snapshot (ticket #40).

When a newer export is imported, the Review Outcomes, kept/replaced links and
Alias decisions saved on earlier Snapshots are proposed for the active one,
never applied silently. An outcome or link is matched by its tickets' numbers
and an Alias by its two employee labels. A proposal compares every source
value of its tickets in the earlier export with the new one: unchanged, it can
be carried forward in one step; changed (or no longer comparable, when the
earlier export is gone and its values were not kept), it shows what changed
and is carried only once the reviewer revalidates it. A decision the new
export cannot hold (a ticket missing, or no rule linking the pair any more)
can only be declined. A carried decision keeps its reviewer, time and
rationale, and its history row names who carried it forward and when;
nothing on the earlier Snapshot changes.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from labour_ticket_analytics.review import ReviewStore
from labour_ticket_analytics.rules import alias_key
from labour_ticket_analytics.store import SnapshotStore

UNCHANGED = "unchanged"
CHANGED = "changed"
NOT_COMPARABLE = "not_comparable"
CANNOT_CARRY = "cannot_carry"

STATUSES = {
    UNCHANGED: "Unchanged in this export",
    CHANGED: "Changed in this export",
    NOT_COMPARABLE: "Cannot be compared",
    CANNOT_CARRY: "Cannot be carried",
}
KIND_LABELS = {"outcome": "Review outcome", "link": "Kept/replaced link", "alias": "Alias decision"}

NOTE = (
    "Decisions saved on an earlier export are proposed here, never applied silently. Tickets are matched by ticket "
    "number and Aliases by their two names. A decision whose tickets changed shows what changed and is carried only "
    "after you check it; nothing on the earlier export changes."
)


def remember_decided(review: ReviewStore, store: SnapshotStore, fingerprint: str) -> None:
    """Keep the source values of every Ticket a decision on this Snapshot names, so they can be compared later."""
    rows = review.decided_rows(fingerprint)
    if rows and store.has_snapshot(fingerprint):
        review.remember_tickets(fingerprint, store.ticket_cells(fingerprint, rows), store.ticket_numbers(fingerprint, rows))


def remember(review: ReviewStore, store: SnapshotStore, fingerprint: str, excel_rows: list[int]) -> None:
    review.remember_tickets(fingerprint, store.ticket_cells(fingerprint, excel_rows), store.ticket_numbers(fingerprint, excel_rows))


def proposals(review: ReviewStore, store: SnapshotStore, target: str) -> dict[str, Any]:
    """The decisions saved elsewhere that the target Snapshot could take, and what reviewers already did with them.

    When several earlier Snapshots decided the same subject, the latest
    decision is proposed. A subject already decided on the target, or
    already carried forward or declined there, is not proposed.
    """
    done = review.carry_records(target)
    handled = {(record["kind"], json.dumps(record["subject"])) for record in done}
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for decision in review.decisions_elsewhere(target):
        key = (decision["kind"], json.dumps(decision["subject"]))
        if key in handled:
            continue
        if key not in latest or decision["recorded_at"] > latest[key]["recorded_at"]:
            latest[key] = decision

    numbers = {number for decision in latest.values() if decision["kind"] != "alias" for number in decision["subject"] if number}
    rows = store.rows_by_ticket_number(target, numbers)
    outcomes_here = set(review.outcomes(target))
    saved_here = review.summary(target)
    links_here = {(link["replaced_row"], link["retained_row"]) for link in saved_here["links"]}
    aliases_here = {tuple(alias["labels"]) for alias in saved_here["aliases"]}
    proposed_aliases = store.alias_proposals(target)
    linked = store.candidate_pairs(target)
    groups = store.possible_duplicate_groups(target)

    found = []
    for decision in sorted(latest.values(), key=lambda item: (item["recorded_at"], item["kind"], json.dumps(item["subject"]))):
        proposal = _proposal(decision)
        if decision["kind"] == "alias":
            labels = tuple(decision["subject"])
            if labels in aliases_here:
                continue
            alias = proposed_aliases.get(alias_key(*labels))
            if alias is None:
                _cannot(proposal, "No name-space variant proposes this Alias in this export, so there is nothing to decide.")
            else:
                proposing = sorted({row for pair in alias["proposed_by"] for row in pair})
                numbers_here = store.ticket_numbers(target, proposing)
                proposal["target"] = {"excel_rows": proposing, "ticket_numbers": [numbers_here.get(row) for row in proposing]}
                proposal["names"] = alias["names"]
            found.append(proposal)
            continue

        reason = _unmatched(decision["subject"], rows)
        if reason:
            _cannot(proposal, reason)
            found.append(proposal)
            continue
        target_rows = [rows[number][0] for number in decision["subject"]]
        proposal["target"] = {"excel_rows": target_rows, "ticket_numbers": list(decision["subject"])}
        if decision["kind"] == "outcome":
            pair = (min(target_rows), max(target_rows))
            if pair in outcomes_here:
                continue
            # The pair key is lower row first; keep the ticket numbers beside their rows.
            if target_rows[0] > target_rows[1]:
                proposal["target"] = {"excel_rows": list(pair), "ticket_numbers": list(reversed(decision["subject"]))}
            if pair not in linked:
                _cannot(
                    proposal,
                    "No rule links these tickets in this export, and a review outcome attaches only to tickets a rule links.",
                )
                found.append(proposal)
                continue
        else:
            if tuple(target_rows) in links_here:
                continue
            if target_rows[1] not in groups.get(target_rows[0], frozenset()):
                _cannot(proposal, "These tickets are no longer in one possible duplicate in this export.")
                found.append(proposal)
                continue
        _compare(proposal, review, store, decision, target)
        found.append(proposal)

    return {
        "proposals": found,
        "carried": [record for record in done if record["action"] == "accepted"],
        "declined": [record for record in done if record["action"] == "declined"],
        "statuses": [{"id": key, "label": label} for key, label in STATUSES.items()],
        "note": NOTE,
    }


def find(review: ReviewStore, store: SnapshotStore, target: str, proposal_id: str) -> dict[str, Any] | None:
    return next((item for item in proposals(review, store, target)["proposals"] if item["id"] == proposal_id), None)


def _proposal(decision: dict[str, Any]) -> dict[str, Any]:
    identity = json.dumps(
        [decision["kind"], decision["subject"], decision["source_fingerprint"], decision["recorded_at"]], separators=(",", ":"),
    )
    return {
        # Opaque, so no ticket number or employee name is ever written into a request path or a log.
        "id": hashlib.sha256(identity.encode()).hexdigest()[:16],
        "kind": decision["kind"],
        "kind_label": KIND_LABELS[decision["kind"]],
        "subject": decision["subject"],
        "source": {"snapshot_fingerprint": decision["source_fingerprint"], "excel_rows": decision["source_rows"]},
        "target": {"excel_rows": [], "ticket_numbers": []},
        "decision": {
            "value": decision["value"],
            "reviewer": decision["reviewer"],
            "recorded_at": decision["recorded_at"],
            "rationale": decision["rationale"],
        },
        "status": UNCHANGED,
        "status_label": STATUSES[UNCHANGED],
        "reason": None,
        "differences": [],
        "needs_revalidation": False,
    }


def _cannot(proposal: dict[str, Any], reason: str) -> None:
    proposal.update(status=CANNOT_CARRY, status_label=STATUSES[CANNOT_CARRY], reason=reason)


def _unmatched(numbers: list[str | None], rows: dict[str, list[int]]) -> str | None:
    for number in numbers:
        if not number:
            return "A ticket in the earlier decision has no ticket number, so it cannot be matched in this export."
        if number not in rows:
            return f"Ticket {number} is not in this export."
        if len(rows[number]) > 1:
            return f"Ticket number {number} appears {len(rows[number])} times in this export, so it cannot be matched."
    return None


def _compare(proposal: dict[str, Any], review: ReviewStore, store: SnapshotStore, decision: dict[str, Any], target: str) -> None:
    source = decision["source_fingerprint"]
    source_rows = decision["source_rows"]
    before = store.ticket_cells(source, source_rows) if store.has_snapshot(source) else {}
    if len(before) < len(source_rows):
        before = {**review.remembered_tickets(source, source_rows), **before}
    if any(row not in before for row in source_rows):
        proposal.update(
            status=NOT_COMPARABLE,
            status_label=STATUSES[NOT_COMPARABLE],
            reason="The earlier export is no longer loaded and its values were not kept, so check these tickets "
            "before carrying the decision forward.",
            needs_revalidation=True,
        )
        return
    after = store.ticket_cells(target, proposal["target"]["excel_rows"])
    by_number = dict(zip(decision["subject"], source_rows))
    differences = []
    for number, target_row in zip(proposal["target"]["ticket_numbers"], proposal["target"]["excel_rows"]):
        old, new = before[by_number[number]], after.get(target_row, {})
        for field in [*new, *(name for name in old if name not in new)]:
            if old.get(field) != new.get(field):
                differences.append({
                    "ticket_number": number,
                    "field": field,
                    "before": (old.get(field) or {}).get("value"),
                    "after": (new.get(field) or {}).get("value"),
                })
    if differences:
        proposal.update(
            status=CHANGED, status_label=STATUSES[CHANGED], differences=differences, needs_revalidation=True,
            reason="Some of these tickets' values changed since the decision was saved; check them before carrying it.",
        )
