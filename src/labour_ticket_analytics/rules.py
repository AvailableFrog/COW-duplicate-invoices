"""Matching rules: Candidates between Ticket pairs, composed into Possible Duplicates.

A rule compares normalized Ticket values and records each match as a
Candidate between two Tickets, carrying the rule, the fields compared, the
strength of the matching evidence and a reason in words. Strength describes
the evidence, never whether anyone was paid or acted deliberately.

Possible Duplicates are the connected components of Candidate edges within one
employee-and-date context, recomposed from the Candidates every time they are
read. Their display identifier is derived from the sorted member ticket
numbers and is never a storage key (ADR 0004).

Changing any rule, its fields or its reason means bumping RULE_VERSION,
because every numeric response carries it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import duckdb

RULE_VERSION = "1.0.0"

# The Strict repeat key: source field -> normalized column. Never ID, Ticket
# Number, timestamps, supervisor or description, which can differ between
# otherwise repeated claims and serve as review evidence instead.
STRICT_KEY = {
    "Employee": "employee_label",
    "Date": "work_date",
    "Job Number": "job_number",
    "Time": "time_key",
    "Regular Hours": "regular_hours",
    "Overtime": "overtime",
    "Double Time": "double_time",
    "Job Work Pay": "job_work_pay",
}


@dataclass(frozen=True)
class Rule:
    id: str
    label: str
    pattern: str
    evidence_strength: str
    fields_compared: tuple[str, ...]
    reason: str

    def payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "pattern": self.pattern,
            "evidence_strength": self.evidence_strength,
            "fields_compared": list(self.fields_compared),
            "reason": self.reason,
        }


STRICT_REPEAT = Rule(
    id="strict_repeat",
    label="Strict repeat",
    pattern="Same claim appears twice",
    evidence_strength="strong",
    fields_compared=tuple(STRICT_KEY),
    reason="Same claim submitted twice: employee, date, job, time and all four hour and pay amounts match.",
)

RULES: dict[str, Rule] = {rule.id: rule for rule in (STRICT_REPEAT,)}

# A Ticket taking part in at least one Candidate; `t` is a ticket_values row.
IN_CANDIDATE_SQL = (
    "EXISTS (SELECT 1 FROM candidates c WHERE c.snapshot_fingerprint = t.snapshot_fingerprint"
    " AND t.excel_row IN (c.first_row, c.second_row))"
)


@dataclass(frozen=True)
class Candidate:
    """One stored link between two Tickets, with the evidence its rule recorded."""

    rule_id: str
    first_row: int
    second_row: int
    fields_compared: tuple[str, ...]
    evidence_strength: str
    reason: str

    def payload(self) -> dict[str, Any]:
        return {
            "excel_rows": [self.first_row, self.second_row],
            "rule_id": self.rule_id,
            "fields_compared": list(self.fields_compared),
            "evidence_strength": self.evidence_strength,
            "reason": self.reason,
        }


def strict_groups_sql() -> str:
    """A query over ticket_values naming every Ticket that shares its complete strict key with another.

    Returns excel_row and strict_group for the Snapshot in $fingerprint. A
    Ticket with any key value missing or invalid (None) is never compared, so
    a blank never equals a blank and is never read as zero.
    """
    columns = ", ".join(STRICT_KEY.values())
    complete = " AND ".join(f"{column} IS NOT NULL" for column in STRICT_KEY.values())
    return f"""SELECT excel_row, dense_rank() OVER (ORDER BY {columns}) AS strict_group FROM (
        SELECT excel_row, {columns}, count(*) OVER (PARTITION BY {columns}) AS key_size
        FROM ticket_values WHERE snapshot_fingerprint = $fingerprint AND {complete}
    ) WHERE key_size > 1"""


def record_candidates(connection: duckdb.DuckDBPyConnection, fingerprint: str) -> None:
    """Run every rule over a Snapshot and store one Candidate per matching Ticket pair, with its evidence."""
    rule = STRICT_REPEAT
    connection.execute(
        f"""INSERT INTO candidates
            (snapshot_fingerprint, rule_id, first_row, second_row, fields_compared, evidence_strength, reason)
        WITH strict AS ({strict_groups_sql()})
        SELECT $fingerprint, $rule_id, a.excel_row, b.excel_row, $fields_compared, $evidence_strength, $reason
        FROM strict a JOIN strict b ON a.strict_group = b.strict_group AND a.excel_row < b.excel_row""",
        {
            "fingerprint": fingerprint,
            "rule_id": rule.id,
            "fields_compared": list(rule.fields_compared),
            "evidence_strength": rule.evidence_strength,
            "reason": rule.reason,
        },
    )


@dataclass(frozen=True)
class Tier:
    rank: int
    id: str
    label: str

    def payload(self) -> dict[str, Any]:
        return {"rank": self.rank, "id": self.id, "label": self.label}


# Review priority, in order (PRD section 4). Priority, not a probability of wrongdoing.
TIERS = (
    Tier(1, "approved_keyed_exact_repeat", "Exact repeat, not flagged: every ticket Approved and Keyed"),
    Tier(2, "approved_beside_unfinished", "Approved beside Pending or not Keyed"),
    Tier(3, "pending_or_flagged", "Pending conflict, or a flagged duplicate whose counterpart is unresolved"),
    Tier(4, "includes_rejected", "Includes a Rejected ticket or an unreadable status"),
)


def tier(members: list[dict[str, Any]], candidates: list[Candidate]) -> Tier:
    """Which review-priority tier a Possible Duplicate falls in, from its evidence and members' source states.

    No Review Outcomes exist yet, so every flagged duplicate's counterpart
    counts as unresolved.
    """
    statuses = {member["status"] for member in members}
    flagged = any(member["flagged_duplicate"] for member in members)
    strong = any(candidate.evidence_strength == "strong" for candidate in candidates)
    approved_keyed = all(member["status"] == "Approved" and member["keyed"] is True for member in members)
    if strong and approved_keyed and not flagged:
        return TIERS[0]
    if flagged:
        return TIERS[2]
    if "Rejected" in statuses or None in statuses:
        return TIERS[3]
    if "Approved" in statuses:
        return TIERS[1]
    return TIERS[2]


def ranked(possible_duplicates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order by tier, then oldest Created, then lowest Ticket Number; number the result from 1.

    A member without a usable Created sorts after those with one. The Excel
    rows are the last key so equal Possible Duplicates can never swap places.
    """

    def key(item: dict[str, Any]) -> tuple[Any, ...]:
        created = [member["created"] for member in item["members"] if member["created"] is not None]
        first = item["members"][0]  # members are sorted by ticket_order
        return (
            item["tier"]["rank"],
            not created,
            min(created, default=""),
            ticket_order(first),
            sorted(member["excel_row"] for member in item["members"]),
        )

    return [{"rank": index, **item} for index, item in enumerate(sorted(possible_duplicates, key=key), start=1)]


def compose(candidates: list[Candidate]) -> list[list[Candidate]]:
    """Group Candidates into connected components; each component's Candidates in a stable order.

    Every rule only links Tickets of one employee and date, so a component
    stays within one employee-and-date context.
    """
    parent: dict[int, int] = {}

    def root(row: int) -> int:
        parent.setdefault(row, row)
        while parent[row] != row:
            parent[row] = parent[parent[row]]
            row = parent[row]
        return row

    for candidate in candidates:
        parent[root(candidate.first_row)] = root(candidate.second_row)
    components: dict[int, list[Candidate]] = {}
    for candidate in sorted(candidates, key=lambda c: (c.first_row, c.second_row, c.rule_id)):
        components.setdefault(root(candidate.first_row), []).append(candidate)
    return list(components.values())


def display_id(members: list[dict[str, Any]]) -> str:
    """'Possible duplicate L225526+L225761': sorted ticket numbers, readable aloud; never a storage key."""
    return "Possible duplicate " + "+".join(ticket_label(member) for member in sorted(members, key=ticket_order))


def ticket_label(member: dict[str, Any]) -> str:
    return member["ticket_number"] or f"row {member['excel_row']}"


def ticket_order(member: dict[str, Any]) -> tuple[bool, str, int]:
    """Lowest Ticket Number first, compared as written; a Ticket without one sorts after, by Excel row."""
    return (member["ticket_number"] is None, member["ticket_number"] or "", member["excel_row"])


def possible_duplicate(candidates: list[Candidate], members: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """One connected component as the Review priorities list shows it, before ranking."""
    rows = sorted({row for candidate in candidates for row in (candidate.first_row, candidate.second_row)})
    member_list = sorted((members[row] for row in rows), key=ticket_order)
    rule_ids = sorted({candidate.rule_id for candidate in candidates})
    priority_tier = tier(member_list, candidates)
    return {
        "display_id": display_id(member_list),
        "tier": priority_tier.payload(),
        # The same population as the unflagged_exact_repeat_count tile, so the label and the tile agree.
        "exact_repeat_not_flagged": priority_tier is TIERS[0],
        "rule_ids": rule_ids,
        "pattern_labels": sorted({RULES[rule_id].pattern for rule_id in rule_ids}),
        "summary": _summary(member_list, candidates),
        "members": member_list,
        "candidates": [candidate.payload() for candidate in candidates],
    }


def _summary(members: list[dict[str, Any]], candidates: list[Candidate]) -> str:
    """The evidence in one or two sentences: each distinct reason, then whose claim and which day."""
    first = members[0]
    context = f"{first['employee'] or 'No employee'}, Date {first['date'] or 'not usable'}"
    jobs = {member["job_number"] for member in members}
    if len(jobs) == 1 and first["job_number"] is not None:
        context += f", Job {first['job_number']}"
    reasons = dict.fromkeys(candidate.reason for candidate in candidates)
    return " ".join(reasons) + f" {context}."
