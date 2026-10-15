"""Matching rules: Candidates between Ticket pairs, composed into Possible Duplicates.

A rule compares normalized Ticket values and records each match as a
Candidate between two Tickets, carrying the rule, the fields compared, the
strength of the matching evidence and a reason in words. Strength describes
the evidence, never whether anyone was paid or acted deliberately.

Rules only compare Tickets inside one search space: the same Date and employee
labels that are equal, differ only in spacing and case, or are joined by a
reviewer-confirmed Alias. Each rule says which of those it accepts; a label
pair differing only in spacing is compared by the Name-space variant alone,
which proposes an Alias and never merges the labels.

Possible Duplicates are the connected components of Candidate edges within one
employee-and-date context, recomposed from the Candidates every time they are
read. Their display identifier is derived from the sorted member ticket
numbers and is never a storage key (ADR 0004).

Changing any rule, its fields or its reason means bumping RULE_VERSION,
because every numeric response carries it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from itertools import combinations
from typing import Any, Iterable

import duckdb

from labour_ticket_analytics.timeparse import TimeParse, compare

RULE_VERSION = "1.2.0"

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
    # Whether a confirmed Alias widens this rule's employee key (PRD section 5: "same employee or confirmed alias").
    accepts_alias: bool = False

    def payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "pattern": self.pattern,
            "evidence_strength": self.evidence_strength,
            "fields_compared": list(self.fields_compared),
            "reason": self.reason,
            "accepts_alias": self.accepts_alias,
        }


STRICT_REPEAT = Rule(
    id="strict_repeat",
    label="Strict repeat",
    pattern="Same claim appears twice",
    evidence_strength="strong",
    fields_compared=tuple(STRICT_KEY),
    reason="Same claim submitted twice: employee, date, job, time and all four hour and pay amounts match.",
)
TIME_TEXT_VARIANT = Rule(
    id="time_text_variant",
    label="Time-text variant",
    pattern="Same claim looks different as text",
    evidence_strength="moderate",
    fields_compared=tuple(STRICT_KEY),
    reason=(
        "Same claim with the time written differently: employee, date, job and all four hour and pay amounts match,"
        " and the Time text differs only in spacing, case or punctuation, or reads as the same work periods."
    ),
)
# Compares the four claim components with Date, Job Number and Time like the Strict repeat, and the
# Employee with every space removed and case-folded. Email is never read: a shared email is no reason.
NAME_SPACE_VARIANT = Rule(
    id="name_space_variant",
    label="Name-space variant",
    pattern="Same claim looks different as text",
    evidence_strength="moderate",
    fields_compared=tuple(STRICT_KEY),
    reason=(
        "Same claim under two spellings of a name: the employee names are equal once spaces and case are ignored,"
        " and date, job, time and all four hour and pay amounts match. This proposes an Alias for a reviewer to"
        " confirm or reject; until then the two labels stay separate."
    ),
)
WORK_PERIOD_CONFLICT = Rule(
    id="work_period_conflict",
    label="Work-period conflict",
    pattern="Possible correction or resubmission",
    evidence_strength="moderate",
    fields_compared=("Employee", "Date", "Time"),
    reason=(
        "Times overlap: work periods read without any assumption intersect on the same day. On its own an overlap"
        " is a conflicting work claim, not proof of a repeated whole ticket."
    ),
    accepts_alias=True,
)
# Pattern 4 retains ambiguous equal-duration cases for review (B). When the assumed reading would
# overlap, as in J, the Candidate is labelled pattern 3 instead, so no label suggests separate work.
AMBIGUOUS_PERIOD_COMPARISON = Rule(
    id="ambiguous_period_comparison",
    label="Ambiguous-period comparison",
    pattern="Equal duration, separate periods",
    evidence_strength="weak",
    fields_compared=tuple(STRICT_KEY),
    reason=(
        "Times need review: same job and all four hour and pay amounts, with times that lack AM/PM, so whether"
        " the work periods overlap cannot be established."
    ),
)

RULES: dict[str, Rule] = {
    rule.id: rule
    for rule in (STRICT_REPEAT, TIME_TEXT_VARIANT, NAME_SPACE_VARIANT, WORK_PERIOD_CONFLICT, AMBIGUOUS_PERIOD_COMPARISON)
}

# A Ticket taking part in at least one Candidate; `t` is a ticket_values row.
IN_CANDIDATE_SQL = (
    "EXISTS (SELECT 1 FROM candidates c WHERE c.snapshot_fingerprint = t.snapshot_fingerprint"
    " AND t.excel_row IN (c.first_row, c.second_row))"
)

# The four claim components, compared one by one and never collapsed into one amount.
CLAIM_FIELDS = ("Regular Hours", "Overtime", "Double Time", "Job Work Pay")


@dataclass(frozen=True)
class Candidate:
    """One stored link between two Tickets, with the evidence its rule recorded."""

    rule_id: str
    first_row: int
    second_row: int
    fields_compared: tuple[str, ...]
    evidence_strength: str
    reason: str
    pattern: str  # the PRD section 5 pattern this match illustrates; usually its rule's

    def payload(self) -> dict[str, Any]:
        return {
            "excel_rows": [self.first_row, self.second_row],
            "rule_id": self.rule_id,
            "fields_compared": list(self.fields_compared),
            "evidence_strength": self.evidence_strength,
            "reason": self.reason,
            "pattern": self.pattern,
        }


@dataclass(frozen=True)
class PairTicket:
    """What the rules compare of one Ticket: its normalized strict-key values and its Time parse result."""

    excel_row: int
    values: dict[str, Any]  # source field -> normalized value (None when blank or invalid), for every STRICT_KEY field
    time: TimeParse
    name: str | None = None  # the Employee as written, for reasons in words; never compared


def alias_key(first_label: str, second_label: str) -> tuple[str, str]:
    """The unordered pair of normalized employee labels an Alias is about, in sorted order."""
    return (first_label, second_label) if first_label <= second_label else (second_label, first_label)


class Aliases:
    """The reviewer-confirmed Aliases of one Snapshot: pairs of employee labels said to name one person.

    An Alias joins exactly the two labels a reviewer confirmed; nothing is
    joined transitively, so no label is ever tied to another that no reviewer
    looked at. Only rules that accept an Alias read it.
    """

    def __init__(self, pairs: Iterable[tuple[str, str]] = ()) -> None:
        self.pairs = frozenset(alias_key(*pair) for pair in pairs)

    def joins(self, first_label: str, second_label: str) -> bool:
        return first_label != second_label and alias_key(first_label, second_label) in self.pairs


NO_ALIASES = Aliases()


def spaceless(label: str) -> str:
    """A normalized employee label with every whitespace character removed: what the Name-space variant compares."""
    return "".join(label.split())


def employee_relation(first: PairTicket, second: PairTicket, aliases: Aliases) -> str:
    """How two Tickets' employee labels relate: the employee half of the search space.

    `same_label`, `confirmed_alias` (two labels a reviewer joined),
    `spacing_differs` (equal once every space is removed, a proposal only),
    `different`, or `unusable` when either label is blank.
    """
    a, b = first.values["Employee"], second.values["Employee"]
    if a is None or b is None:
        return "unusable"
    if a == b:
        return "same_label"
    if aliases.joins(a, b):
        return "confirmed_alias"
    return "spacing_differs" if spaceless(a) == spaceless(b) else "different"


# The relations a rule that accepts a confirmed Alias compares; every other rule except the
# Name-space variant compares one label only.
ONE_EMPLOYEE = ("same_label", "confirmed_alias")


@dataclass(frozen=True)
class Verdict:
    """One rule's answer for one Ticket pair: whether it matched, and why or why not in words."""

    rule: Rule
    matched: bool
    reason: str
    pattern: str | None = None  # when the match illustrates another pattern than its rule's

    def candidate(self, first: PairTicket, second: PairTicket) -> Candidate:
        rule = self.rule
        return Candidate(
            rule.id, first.excel_row, second.excel_row, rule.fields_compared, rule.evidence_strength, self.reason,
            self.pattern or rule.pattern,
        )

    def payload(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule.id,
            "rule_label": self.rule.label,
            "matched": self.matched,
            "evidence_strength": self.rule.evidence_strength,
            "fields_compared": list(self.rule.fields_compared),
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


def pair_tickets(
    connection: duckdb.DuckDBPyConnection, fingerprint: str, parses: dict[int, TimeParse], rows: list[int] | None = None,
) -> dict[int, PairTicket]:
    """The comparable values of a Snapshot's Tickets (or only `rows`), by Excel row."""
    query = (
        f"SELECT excel_row, employee_name, {', '.join(STRICT_KEY.values())} FROM ticket_values"
        " WHERE snapshot_fingerprint = $fingerprint"
    )
    parameters: dict[str, Any] = {"fingerprint": fingerprint}
    if rows is not None:
        query += " AND list_contains($rows, excel_row)"
        parameters["rows"] = rows
    return {
        row[0]: PairTicket(row[0], dict(zip(STRICT_KEY, row[2:])), parses[row[0]], row[1])
        for row in connection.execute(query + " ORDER BY excel_row", parameters).fetchall()
    }


def in_search_space(first: PairTicket, second: PairTicket, aliases: Aliases = NO_ALIASES) -> bool:
    """Where rules look: the same Date as recorded, and employee labels that are equal, differ only in spacing,
    or are joined by a confirmed Alias. A search space, never a rule, so it links nothing by itself.

    This is the one place the search space is defined; each rule then says
    which employee relation it accepts.
    """
    date = first.values["Date"]
    return (
        date is not None and date == second.values["Date"]
        and employee_relation(first, second, aliases) in ("same_label", "confirmed_alias", "spacing_differs")
    )


def verdicts(first: PairTicket, second: PairTicket, aliases: Aliases = NO_ALIASES) -> list[Verdict]:
    """Every rule's verdict on a pair inside the search space, in RULES order; `first` is the lower Excel row.

    When the whole claim repeats (a Strict repeat, Time-text variant or
    Name-space variant), the pair's overlap is part of that repeat, so its
    Work-period conflict takes the repeat's pattern and adds no "Possible
    correction or resubmission".
    """
    relation = employee_relation(first, second, aliases)
    strict, variant, name, conflict, ambiguous = (
        _strict_repeat(first, second),
        _time_text_variant(first, second, relation),
        _name_space_variant(first, second),
        _work_period_conflict(first, second, relation),
        _ambiguous_period_comparison(first, second, relation),
    )
    repeat = next((verdict for verdict in (strict, variant, name) if verdict.matched), None)
    if conflict.matched and repeat is not None:
        conflict = replace(conflict, pattern=repeat.rule.pattern)
    return [strict, variant, name, conflict, ambiguous]


def explain(first: PairTicket, second: PairTicket, aliases: Aliases = NO_ALIASES) -> dict[str, Any]:
    """Why two Tickets are or are not linked: every rule's verdict and a summary in words.

    Outside the employee-and-date search space no rule compares them. Inside
    it, equal hours alone never link two Tickets, and a pair no rule links is
    explained by how its work periods compare.
    """
    relation = employee_relation(first, second, aliases)
    if not in_search_space(first, second, aliases):
        reason = (
            "Not compared: the rules only compare tickets on the same Date whose employee labels are the same,"
            " differ only in spacing and case, or are joined by a confirmed Alias."
        )
        return {
            "same_employee_and_date": False,
            "employee_relation": relation,
            "linked": False,
            "rules": [Verdict(rule, False, reason).payload() for rule in RULES.values()],
            "summary": reason,
        }
    found = verdicts(first, second, aliases)
    matched = [verdict for verdict in found if verdict.matched]
    if matched:
        summary = "Linked by " + _listed([verdict.rule.label for verdict in matched]) + ". " + " ".join(
            verdict.reason for verdict in matched
        )
    else:
        conflict = next(verdict for verdict in found if verdict.rule is WORK_PERIOD_CONFLICT)
        summary = f"Not linked: no rule matches. {conflict.reason}"
        if _unequal(first, second, CLAIM_FIELDS) is None:
            summary += " Their hours and pay are equal, but equal hours on the same day never link tickets on their own."
    return {
        "same_employee_and_date": True,
        "employee_relation": relation,
        "linked": bool(matched),
        "rules": [verdict.payload() for verdict in found],
        "summary": summary,
    }


def find_candidates(
    connection: duckdb.DuckDBPyConnection, fingerprint: str, parses: dict[int, TimeParse], aliases: Aliases = NO_ALIASES,
) -> list[Candidate]:
    """Run every rule over each Ticket pair in the employee-and-date search space: one Candidate per rule per
    matching pair, with its evidence. A pair several rules match keeps every rule's reason."""
    by_date: dict[Any, list[PairTicket]] = {}
    for ticket in pair_tickets(connection, fingerprint, parses).values():
        if ticket.values["Date"] is not None:
            by_date.setdefault(ticket.values["Date"], []).append(ticket)
    return [
        verdict.candidate(first, second)
        for tickets in by_date.values()
        for first, second in combinations(tickets, 2)  # in Excel-row order, so first is the lower row
        if in_search_space(first, second, aliases)
        for verdict in verdicts(first, second, aliases)
        if verdict.matched
    ]


def record_candidates(
    connection: duckdb.DuckDBPyConnection, fingerprint: str, parses: dict[int, TimeParse], aliases: Aliases = NO_ALIASES,
) -> list[Candidate]:
    """Find the Snapshot's Candidates under the given confirmed Aliases and store them; returns what was stored."""
    found = find_candidates(connection, fingerprint, parses, aliases)
    if found:
        connection.executemany(
            "INSERT INTO candidates (snapshot_fingerprint, rule_id, first_row, second_row, fields_compared,"
            " evidence_strength, reason, pattern) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                [
                    fingerprint, c.rule_id, c.first_row, c.second_row, list(c.fields_compared), c.evidence_strength,
                    c.reason, c.pattern,
                ]
                for c in found
            ],
        )
    return found


def _strict_repeat(first: PairTicket, second: PairTicket) -> Verdict:
    rule = STRICT_REPEAT
    problem = _unequal(first, second, tuple(STRICT_KEY))
    if problem:
        return Verdict(rule, False, f"Not a strict repeat: {problem}.")
    return Verdict(rule, True, rule.reason)


def _time_text_variant(first: PairTicket, second: PairTicket, relation: str) -> Verdict:
    """Same claim, Time differing as text but equivalent: same Confident Intervals, or the same time tokens."""
    rule = TIME_TEXT_VARIANT
    problem = (
        _one_label(relation) or _unequal(first, second, ("Job Number", *CLAIM_FIELDS)) or _same_time_text(first, second)
    )
    if problem:
        return Verdict(rule, False, f"Not a time-text variant: {problem}.")
    differences = _token_differences(first.time, second.time)
    same_periods = (
        first.time.status == second.time.status == "confident"
        and first.time.confident_intervals() == second.time.confident_intervals()
    )
    if not differences and not same_periods:
        return Verdict(
            rule, False,
            "Not a time-text variant: the Time texts differ beyond spacing, case or punctuation and do not read as"
            " the same Confident Intervals.",
        )
    conditions = []
    if differences:
        conditions.append(f"the Time text differs only in {_listed(differences)} around the same times")
    if same_periods:
        conditions.append(f"both read as the same work periods ({_intervals(first.time.confident_intervals())})")
    return Verdict(rule, True, "Same claim with the time written differently: " + ", and ".join(conditions) + ".")


def _name_space_variant(first: PairTicket, second: PairTicket) -> Verdict:
    """Two employee labels equal once every space is removed, with the whole claim otherwise equal.

    It proposes an Alias and is a Candidate itself; it never merges the
    labels, and it reads the same whether the Alias is proposed, confirmed or
    rejected. Email is never compared.
    """
    rule = NAME_SPACE_VARIANT
    a, b = first.values["Employee"], second.values["Employee"]
    if a is None or b is None:
        problem = "Employee is blank or unusable on a ticket"
    elif a == b:
        problem = "the employee labels are the same, so there is no name variation to propose"
    elif spaceless(a) != spaceless(b):
        problem = "the employee names differ beyond spacing and case"
    else:
        problem = _unequal(first, second, ("Date", "Job Number", "Time", *CLAIM_FIELDS))
    if problem:
        return Verdict(rule, False, f"Not a name-space variant: {problem}.")
    return Verdict(
        rule, True,
        f"Same claim under two spellings of a name: “{first.name}” and “{second.name}” are equal once spaces and case"
        " are ignored, and date, job, time and all four hour and pay amounts match. This proposes an Alias for a"
        " reviewer to confirm or reject; until then they stay two employee labels.",
    )


def _work_period_conflict(first: PairTicket, second: PairTicket, relation: str) -> Verdict:
    """Confident Intervals intersect on the same day; jobs and claim components may differ.

    One employee label, or two joined by a confirmed Alias.
    """
    rule = WORK_PERIOD_CONFLICT
    if relation not in ONE_EMPLOYEE:
        return Verdict(
            rule, False,
            "Not compared for overlap: the employee labels differ and no confirmed Alias joins them.",
        )
    comparison = compare(first.time, second.time)
    result = comparison["result"]
    if result == "overlap":
        jobs = _job_phrase(first, second)
        alias = f" under the confirmed Alias “{first.name}” / “{second.name}”" if relation == "confirmed_alias" else ""
        shared = _spans(comparison["intersection"])
        return Verdict(
            rule, True,
            f"Times overlap{jobs}{alias}: the Confident Intervals share {shared}"
            f" ({_duration(comparison['overlap_minutes'])}), a conflicting work claim rather than proof of a repeated"
            " whole ticket.",
        )
    if result == "separate":
        return Verdict(
            rule, False,
            "Times do not overlap: every period on both tickets is a Confident Interval"
            f" ({_intervals(first.time.confident_intervals())} and {_intervals(second.time.confident_intervals())})"
            " and they do not intersect, so these are separate work periods.",
        )
    if result == "ambiguous":
        return Verdict(
            rule, False,
            "No Confident Intervals intersect, and a period without AM/PM can neither establish nor rule out overlap.",
        )
    return Verdict(rule, False, "The times cannot be compared: a ticket has no readable, unflagged work period.")


def _ambiguous_period_comparison(first: PairTicket, second: PairTicket, relation: str) -> Verdict:
    """Same nonzero job and claim, distinct Time text whose comparison stays unresolved without AM/PM."""
    rule = AMBIGUOUS_PERIOD_COMPARISON
    problem = (
        _one_label(relation) or _unequal(first, second, ("Job Number", *CLAIM_FIELDS)) or _same_time_text(first, second)
    )
    if not problem and first.values["Job Number"] == 0:
        problem = "the Job Number is 0, and this comparison needs the same nonzero job"
    if problem:
        return Verdict(rule, False, f"Not an ambiguous-period comparison: {problem}.")
    comparison = compare(first.time, second.time)
    if comparison["result"] != "ambiguous":
        why = {
            "overlap": "the Confident Intervals already overlap, which the Work-period conflict rule reports",
            "separate": "every period is a Confident Interval, so nothing needs to be assumed",
            "undetermined": "a ticket has no readable, unflagged work period, so there is nothing to compare",
        }[comparison["result"]]
        return Verdict(rule, False, f"Not an ambiguous-period comparison: {why}.")
    assumed = comparison["intersection"]
    reading = (
        f"Under the assumed reading they would overlap {_spans(assumed)} (assumed, not established)."
        if assumed else "Under the assumed reading they would not overlap (assumed, not established)."
    )
    return Verdict(
        rule, True,
        "Same job and all four hour and pay amounts, with a time written without AM/PM, so whether the work"
        f" periods overlap cannot be established and the times need review. {reading}",
        WORK_PERIOD_CONFLICT.pattern if assumed else None,
    )


def _one_label(relation: str) -> str | None:
    """Why a rule that compares one employee label does not apply, or None when the labels are the same."""
    if relation == "same_label":
        return None
    return "the employee labels differ, and this rule compares one label only (an Alias does not widen it)"


def _unequal(first: PairTicket, second: PairTicket, fields: tuple[str, ...]) -> str | None:
    """Why the fields do not all match, or None when every one is usable and equal on both Tickets."""
    unusable = [field for field in fields if first.values[field] is None or second.values[field] is None]
    if unusable:
        return f"{_listed(unusable)} {'is' if len(unusable) == 1 else 'are'} blank or unusable on a ticket"
    differing = [field for field in fields if first.values[field] != second.values[field]]
    if differing:
        return f"{_listed(differing)} {'differs' if len(differing) == 1 else 'differ'}"
    return None


def _same_time_text(first: PairTicket, second: PairTicket) -> str | None:
    """Why the Time cells are not distinct, usable text-or-value pairs, or None when they are."""
    if first.values["Time"] is None or second.values["Time"] is None:
        return "Time is blank or unusable on a ticket"
    if first.values["Time"] == second.values["Time"]:
        return "the Time text is the same after trimming, case and spacing, which the Strict repeat rule compares"
    return None


# Runs of digits and runs of letters: the time tokens. Everything else is spacing or punctuation.
TOKEN = re.compile(r"\d+|[^\W\d_]+")


def _token_differences(first: TimeParse, second: TimeParse) -> list[str]:
    """How two Time texts with the same time-token sequence differ: spacing, case and/or punctuation.

    Empty when either is not text, has no tokens, or the token sequences differ.
    """
    if first.raw_type != "str" or second.raw_type != "str":
        return []
    a, b = str(first.raw_value), str(second.raw_value)
    tokens = TOKEN.findall(a.casefold())
    if not tokens or tokens != TOKEN.findall(b.casefold()):
        return []

    def spacing(text: str) -> str:
        # Where the spaces fall between the other characters. With the same punctuation count each
        # mark keeps its place; with a different count the marks are dropped, so an added or removed
        # mark is reported as punctuation and not also as spacing.
        collapsed = " ".join(text.casefold().split())
        return re.sub(r"[^\w\s]", "\u00b7" if same_marks else "", collapsed)

    def letters(text: str) -> list[str]:
        return [character for character in text if character.isalnum()]

    def punctuation(text: str) -> list[str]:
        return [character for character in text if not character.isalnum() and not character.isspace()]

    same_marks = len(punctuation(a)) == len(punctuation(b))
    # Case alone never reaches here: the Strict repeat compares Time case-folded.
    return [
        name for name, differs in (
            ("spacing", spacing(a) != spacing(b)),
            ("case", letters(a) != letters(b)),
            ("punctuation", punctuation(a) != punctuation(b)),
        ) if differs
    ]


def _job_phrase(first: PairTicket, second: PairTicket) -> str:
    a, b = first.values["Job Number"], second.values["Job Number"]
    if a is None or b is None:
        return ""
    return " on the same job" if a == b else " on different jobs"


def _spans(payload: list[dict[str, str]]) -> str:
    """Intervals as a comparison payload gives them, in words: "07:30-11:30, 14:30-16:30"."""
    return ", ".join(f"{item['start']}-{item['end']}" for item in payload)


def _intervals(intervals: list[tuple[int, int]]) -> str:
    return ", ".join(f"{_clock(start)}-{_clock(end)}" for start, end in intervals) or "none"


def _clock(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _duration(minutes: int) -> str:
    hours, rest = divmod(minutes, 60)
    parts = ([f"{hours} hour{'s' if hours != 1 else ''}"] if hours else []) + (
        [f"{rest} minute{'s' if rest != 1 else ''}"] if rest else []
    )
    return " ".join(parts)


def _listed(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


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
    Tier(2, "approved_beside_unfinished", "Approved beside Pending or not Keyed, or Approved and Keyed without an exact repeat"),
    Tier(3, "pending_or_flagged", "Pending conflict, or a flagged duplicate whose counterpart is unresolved"),
    Tier(4, "includes_rejected", "Includes a Rejected ticket or an unreadable status"),
)


def tier(members: list[dict[str, Any]], candidates: list[Candidate]) -> Tier:
    """Which review-priority tier a Possible Duplicate falls in, from its evidence and members' source states.

    No Review Outcomes exist yet, so every flagged duplicate's counterpart
    counts as unresolved. Only the Strict repeat rule gives strong evidence,
    so tier 1 holds exact repeats alone; Approved and Keyed Tickets linked
    only by a weaker rule fall to tier 2.
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

    Every rule only links Tickets inside one employee-and-date search space,
    so a component stays within one such context.
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
        "pattern_labels": list(dict.fromkeys(candidate.pattern for candidate in sorted(candidates, key=_rule_order))),
        "summary": _summary(member_list, candidates),
        "members": member_list,
        "candidates": [candidate.payload() for candidate in candidates],
    }


def _rule_order(candidate: Candidate) -> int:
    return list(RULES).index(candidate.rule_id)


def _summary(members: list[dict[str, Any]], candidates: list[Candidate]) -> str:
    """The evidence in a few sentences: each rule's reason, a chain note, then whose claim and which day.

    Tickets joined only through another Ticket need not repeat one another,
    so a possible duplicate of three or more says so and never infers that
    any Ticket is surplus.
    """
    first = members[0]
    names = _listed(list(dict.fromkeys(member["employee"] or "No employee" for member in members)))
    context = f"{names}, Date {first['date'] or 'not usable'}"
    jobs = {member["job_number"] for member in members}
    if len(jobs) == 1 and first["job_number"] is not None:
        context += f", Job {first['job_number']}"
    found = {candidate.rule_id for candidate in candidates}
    reasons = [rule.reason for rule in RULES.values() if rule.id in found]
    if len(members) > 2:
        reasons.append(
            f"{len(members)} tickets linked in a chain by {len(candidates)} links: tickets joined only through"
            " another ticket need not repeat each other."
        )
    return " ".join(reasons) + f" {context}."
