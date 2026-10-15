"""Local review data: Review Outcomes on Ticket pairs, kept/replaced links, Alias decisions and their history.

A Review Outcome attaches to the order-independent pair of Tickets behind a
Candidate, keyed by the Snapshot fingerprint and the pair's two Excel rows,
lower first (decision-log entry 33). The pair's ticket numbers are stored
beside it for a later carry-forward to a new export, never as the key. A
replacement link attaches to individual Tickets: one replaced Ticket and one
kept (retained) Ticket, and a replaced Ticket may have several kept ones. A
Possible Duplicate only displays the outcomes of its member pairs; it is never
a key (ADR 0004). An Alias decision attaches to the unordered pair of
normalized employee labels a Name-space variant proposed, within one Snapshot:
a reviewer confirms or rejects it, and a confirmed Alias widens the employee
key of the rules that accept one the next time the rules run.

Everything here lives in one local DuckDB file in the data directory, apart
from the in-memory Snapshot tables, and nothing is ever written to the
workbook (ADR 0002). Every save that changes an outcome, and every link made
or removed, appends a history row with the reviewer label, the time, the
previous and new values and the rationale. An outcome or a note has no
numerical effect: only a replacement link names a Ticket an adjusted figure
may leave out. An Alias changes which Tickets the rules compare, never a count
of employee labels.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import duckdb

REVIEW_FILE_NAME = "review.duckdb"
SCHEMA_VERSION = 3


@dataclass(frozen=True)
class OutcomeValue:
    id: str
    label: str
    definition: str

    def payload(self) -> dict[str, str]:
        return {"id": self.id, "label": self.label, "definition": self.definition}


# The glossary's Review Outcomes, in display order.
OUTCOME_VALUES = (
    OutcomeValue("not_reviewed", "Not reviewed", "No judgement yet."),
    OutcomeValue(
        "confirmed_duplicate", "Confirmed duplicate",
        "The reviewer agrees the tickets repeat the same claim. It says nothing about payment.",
    ),
    OutcomeValue("not_a_duplicate", "Not a duplicate", "The reviewer judged the tickets to be separate work."),
    OutcomeValue(
        "replacement_ticket", "Replacement ticket",
        "One ticket corrects or replaces another; link the kept and replaced tickets.",
    ),
    OutcomeValue("needs_follow_up", "Needs follow-up", "A question remains open."),
)
OUTCOMES = {value.id: value for value in OUTCOME_VALUES}
NOT_REVIEWED = OUTCOMES["not_reviewed"]
# The outcomes that settle how two Tickets relate, so a flagged duplicate's counterpart on that pair is resolved.
# Not a duplicate says the pair is not the relationship; Needs follow-up leaves it open.
SETTLING_OUTCOMES = ("confirmed_duplicate", "replacement_ticket")

# An Alias proposal's states, in display order. Proposed is the state before any decision is saved.
ALIAS_DECISION_VALUES = (
    OutcomeValue(
        "proposed", "Proposed",
        "A rule found the same claim under both names. Until a reviewer confirms it they stay two employee labels.",
    ),
    OutcomeValue(
        "confirmed", "Confirmed",
        "The reviewer says both labels name one person. The Work-period conflict rule then compares their tickets as"
        " one employee; the employee-label count still counts two labels.",
    ),
    OutcomeValue(
        "rejected", "Rejected",
        "The reviewer does not accept that the labels name one person; nothing is compared across them beyond the"
        " proposal itself.",
    ),
)
ALIAS_DECISIONS = {value.id: value for value in ALIAS_DECISION_VALUES}
PROPOSED = ALIAS_DECISIONS["proposed"]
# What a reviewer can save; Proposed is only ever the state before a decision.
SAVED_ALIAS_DECISIONS = ("confirmed", "rejected")

# What no screen may say (GLOSSARY "Never claimed"), so no reviewer text may carry it either.
BANNED_PHRASES = ("paid twice", "missed duplicate", "fraud")
MAX_LENGTHS = {"reviewer": 80, "note": 4000, "reference": 500, "rationale": 1000}

SCHEMA = """
CREATE TABLE IF NOT EXISTS review_store (schema_version INTEGER NOT NULL);
CREATE SEQUENCE IF NOT EXISTS review_history_entry START 1;
CREATE TABLE IF NOT EXISTS review_outcomes (
    snapshot_fingerprint VARCHAR NOT NULL,
    first_row INTEGER NOT NULL,
    second_row INTEGER NOT NULL,
    first_ticket_number VARCHAR,
    second_ticket_number VARCHAR,
    outcome VARCHAR NOT NULL,
    note VARCHAR NOT NULL,
    reference VARCHAR NOT NULL,
    reviewer VARCHAR NOT NULL,
    recorded_at VARCHAR NOT NULL,
    PRIMARY KEY (snapshot_fingerprint, first_row, second_row),
    CHECK (first_row < second_row)
);
CREATE TABLE IF NOT EXISTS replacement_links (
    snapshot_fingerprint VARCHAR NOT NULL,
    replaced_row INTEGER NOT NULL,
    retained_row INTEGER NOT NULL,
    replaced_ticket_number VARCHAR,
    retained_ticket_number VARCHAR,
    reviewer VARCHAR NOT NULL,
    recorded_at VARCHAR NOT NULL,
    rationale VARCHAR NOT NULL,
    PRIMARY KEY (snapshot_fingerprint, replaced_row, retained_row),
    CHECK (replaced_row <> retained_row)
);
CREATE TABLE IF NOT EXISTS review_history (
    entry BIGINT PRIMARY KEY DEFAULT nextval('review_history_entry'),
    snapshot_fingerprint VARCHAR NOT NULL,
    kind VARCHAR NOT NULL,
    excel_rows INTEGER[] NOT NULL,
    ticket_numbers VARCHAR[] NOT NULL,
    reviewer VARCHAR NOT NULL,
    recorded_at VARCHAR NOT NULL,
    previous_value JSON,
    new_value JSON,
    rationale VARCHAR NOT NULL,
    employee_labels VARCHAR[]
);
CREATE SEQUENCE IF NOT EXISTS saved_view_id START 1;
CREATE TABLE IF NOT EXISTS saved_views (
    id BIGINT PRIMARY KEY DEFAULT nextval('saved_view_id'),
    name VARCHAR NOT NULL,
    kind VARCHAR NOT NULL,
    state JSON NOT NULL,
    snapshot_fingerprint VARCHAR NOT NULL,
    as_of VARCHAR NOT NULL,
    versions JSON NOT NULL,
    aliases JSON NOT NULL,
    created_at VARCHAR NOT NULL,
    updated_at VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS alias_decisions (
    snapshot_fingerprint VARCHAR NOT NULL,
    first_label VARCHAR NOT NULL,
    second_label VARCHAR NOT NULL,
    decision VARCHAR NOT NULL,
    reviewer VARCHAR NOT NULL,
    recorded_at VARCHAR NOT NULL,
    rationale VARCHAR NOT NULL,
    PRIMARY KEY (snapshot_fingerprint, first_label, second_label),
    CHECK (first_label < second_label)
);
"""

# From schema version 1 (ticket #8): history rows gain the label pair an Alias decision is about.
MIGRATIONS = {
    1: "ALTER TABLE review_history ADD COLUMN IF NOT EXISTS employee_labels VARCHAR[];",
    # From schema version 2 (ticket #39): saved views, a new table the schema itself creates.
    2: "SELECT 1;",
}


class ReviewError(ValueError):
    """A review request that cannot be saved; code and field say why, as the filter errors do."""

    def __init__(self, code: str, field_name: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.field = field_name
        self.status = status

    def payload(self) -> dict[str, str]:
        return {"code": self.code, "field": self.field, "message": str(self)}


class ReviewStoreUnavailable(RuntimeError):
    """The review file cannot be used: another running copy holds it, or it has another schema version."""


def pair_key(first_row: int, second_row: int) -> tuple[int, int]:
    """The order-independent pair: its two Excel rows, lower first."""
    return (first_row, second_row) if first_row < second_row else (second_row, first_row)


def outcome_label(outcome_id: str) -> dict[str, str]:
    return {"id": outcome_id, "label": OUTCOMES[outcome_id].label}


def clean_text(field_name: str, value: str, *, required: bool = False) -> str:
    """Reviewer text, trimmed at the ends, within its length limit and free of the phrases no screen may show."""
    text = value.strip()
    if required and not text:
        raise ReviewError("missing_value", field_name, f"give a {field_name}")
    if len(text) > MAX_LENGTHS[field_name]:
        raise ReviewError("too_long", field_name, f"the {field_name} is longer than {MAX_LENGTHS[field_name]} characters")
    folded = text.casefold()
    for phrase in BANNED_PHRASES:
        if phrase in folded:
            raise ReviewError(
                "banned_phrase",
                field_name,
                f"the {field_name} says {phrase!r}, which no screen may show: the export holds no payment records "
                "and cannot show whether a ticket was handled elsewhere. Use Confirmed duplicate, Exact repeat or "
                "Needs follow-up wording instead.",
            )
    return text


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class ReviewStore:
    """The local review file, opened once per launch and shared by request threads under one lock."""

    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            self.connection = duckdb.connect(database=str(path))
        except duckdb.IOException as error:
            raise ReviewStoreUnavailable(
                f"the review store {path} could not be opened ({error}); "
                "if another copy of the application is running with the same --data-dir, stop it first"
            ) from error
        self._lock = threading.RLock()
        # Bumped by every committed change to outcomes, links or Alias decisions, so a cached Explore result
        # made under earlier review data is never served after a change (decision-log entry 84).
        self._revision = 0
        self.connection.execute(SCHEMA)
        row = self.connection.execute("SELECT max(schema_version) FROM review_store").fetchone()
        if row[0] is None:
            self.connection.execute("INSERT INTO review_store VALUES (?)", [SCHEMA_VERSION])
        elif row[0] in MIGRATIONS:
            # An older review file keeps everything it holds and gains the new tables and columns.
            with self._transaction():
                self.connection.execute(MIGRATIONS[row[0]])
                self.connection.execute("UPDATE review_store SET schema_version = ?", [SCHEMA_VERSION])
        elif row[0] != SCHEMA_VERSION:
            raise ReviewStoreUnavailable(f"the review store {path} has schema version {row[0]}, expected {SCHEMA_VERSION}")

    @classmethod
    def in_data_dir(cls, data_dir: Path) -> ReviewStore:
        data_dir.mkdir(parents=True, exist_ok=True)
        return cls(data_dir / REVIEW_FILE_NAME)

    def close(self) -> None:
        with self._lock:
            self.connection.close()

    @property
    def revision(self) -> int:
        """How many changes this launch has committed: the review configuration a cached result was made under."""
        with self._lock:
            return self._revision

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        """One atomic change: a value and its history row are saved together or not at all."""
        self.connection.execute("BEGIN TRANSACTION")
        try:
            yield
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise
        self.connection.execute("COMMIT")
        self._revision += 1

    # Outcomes

    def outcome(
        self, fingerprint: str, first_row: int, second_row: int, ticket_numbers: dict[int, str | None]
    ) -> dict[str, Any]:
        """The pair's current outcome, Not reviewed when none was saved, with the pair's history."""
        first, second = pair_key(first_row, second_row)
        with self._lock:
            record = self._outcomes(fingerprint, [(first, second)]).get((first, second))
            history = self._history(fingerprint, kind="outcome", excel_rows=[first, second])
        unsaved = _unsaved(first, second, [ticket_numbers.get(first), ticket_numbers.get(second)])
        return {**(record or unsaved), "history": history}

    def outcomes(self, fingerprint: str, pairs: Iterable[tuple[int, int]] | None = None) -> dict[tuple[int, int], dict[str, Any]]:
        """Saved outcomes by pair key; all of the Snapshot's when pairs is None."""
        with self._lock:
            return self._outcomes(fingerprint, None if pairs is None else [pair_key(*pair) for pair in pairs])

    def _outcomes(self, fingerprint: str, pairs: list[tuple[int, int]] | None) -> dict[tuple[int, int], dict[str, Any]]:
        query = (
            "SELECT first_row, second_row, first_ticket_number, second_ticket_number, outcome, note, reference,"
            " reviewer, recorded_at FROM review_outcomes WHERE snapshot_fingerprint = ?"
        )
        rows = self.connection.execute(query + " ORDER BY first_row, second_row", [fingerprint]).fetchall()
        wanted = None if pairs is None else set(pairs)
        return {
            (row[0], row[1]): {
                "excel_rows": [row[0], row[1]],
                "ticket_numbers": [row[2], row[3]],
                "outcome": outcome_label(row[4]),
                "note": row[5],
                "reference": row[6],
                "reviewer": row[7],
                "recorded_at": row[8],
                "saved": True,
            }
            for row in rows
            if wanted is None or (row[0], row[1]) in wanted
        }

    def settled_pairs(self, fingerprint: str) -> set[tuple[int, int]]:
        """The Ticket pairs (lower row first) a reviewer settled: a Confirmed duplicate or Replacement ticket outcome,
        or a kept/replaced link between the two. Only the rules' tiers read this, never a figure."""
        with self._lock:
            outcomes = self.connection.execute(
                "SELECT first_row, second_row FROM review_outcomes WHERE snapshot_fingerprint = ? AND list_contains(?, outcome)",
                [fingerprint, list(SETTLING_OUTCOMES)],
            ).fetchall()
            links = [pair_key(link["replaced_row"], link["retained_row"]) for link in self._links(fingerprint)]
        return {(first, second) for first, second in outcomes} | set(links)

    def replaced_rows(self, fingerprint: str) -> list[int]:
        """The Tickets an explicit kept/replaced link marks as replaced: the only ones an adjusted figure may leave out."""
        with self._lock:
            return sorted({link["replaced_row"] for link in self._links(fingerprint)})

    def save_outcome(
        self,
        fingerprint: str,
        first_row: int,
        second_row: int,
        ticket_numbers: dict[int, str | None],
        *,
        outcome: str,
        note: str,
        reference: str,
        reviewer: str,
        rationale: str,
    ) -> dict[str, Any]:
        """Set a pair's outcome, note and reference; a change appends a history row.

        Saving exactly what is already saved changes nothing and appends no
        history. Changing a saved outcome, note or reference is a revision,
        which needs a rationale.
        """
        if outcome not in OUTCOMES:
            raise ReviewError("unknown_outcome", "outcome", f"{outcome!r} is not a Review Outcome; use one of {', '.join(OUTCOMES)}")
        reviewer = clean_text("reviewer", reviewer, required=True)
        note = clean_text("note", note)
        reference = clean_text("reference", reference)
        rationale = clean_text("rationale", rationale)
        first, second = pair_key(first_row, second_row)
        numbers = [ticket_numbers.get(first), ticket_numbers.get(second)]
        new_value = {"outcome": outcome_label(outcome), "note": note, "reference": reference}
        with self._lock:
            previous = self._outcomes(fingerprint, [(first, second)]).get((first, second))
            previous_value = (
                {"outcome": previous["outcome"], "note": previous["note"], "reference": previous["reference"]}
                if previous else None
            )
            changed = previous_value != new_value
            if changed and previous is not None and not rationale:
                raise ReviewError(
                    "rationale_required", "rationale", "give a reason for changing a saved outcome, note or reference"
                )
            if changed:
                recorded_at = _now()
                with self._transaction():
                    self.connection.execute(
                        "INSERT OR REPLACE INTO review_outcomes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        [fingerprint, first, second, *numbers, outcome, note, reference, reviewer, recorded_at],
                    )
                    self._append_history(
                        fingerprint, "outcome", [first, second], numbers, reviewer, recorded_at,
                        previous_value, new_value, rationale,
                    )
            record = self._outcomes(fingerprint, [(first, second)])[(first, second)]
            history = self._history(fingerprint, kind="outcome", excel_rows=[first, second])
        return {**record, "history": history, "changed": changed}

    # Replacement links

    def _links(self, fingerprint: str, excel_rows: Iterable[int] | None = None) -> list[dict[str, Any]]:
        """Links with either Ticket among excel_rows (all of the Snapshot's when None), oldest first."""
        rows = self.connection.execute(
            "SELECT replaced_row, retained_row, replaced_ticket_number, retained_ticket_number, reviewer, recorded_at,"
            " rationale FROM replacement_links WHERE snapshot_fingerprint = ? ORDER BY recorded_at, replaced_row, retained_row",
            [fingerprint],
        ).fetchall()
        wanted = None if excel_rows is None else set(excel_rows)
        return [
            {
                "replaced_row": row[0],
                "retained_row": row[1],
                "replaced_ticket_number": row[2],
                "retained_ticket_number": row[3],
                "reviewer": row[4],
                "recorded_at": row[5],
                "rationale": row[6],
            }
            for row in rows
            if wanted is None or row[0] in wanted or row[1] in wanted
        ]

    def _link(self, fingerprint: str, replaced_row: int, retained_row: int) -> dict[str, Any] | None:
        return next(
            (
                link for link in self._links(fingerprint)
                if (link["replaced_row"], link["retained_row"]) == (replaced_row, retained_row)
            ),
            None,
        )

    def link(
        self,
        fingerprint: str,
        replaced_row: int,
        retained_row: int,
        ticket_numbers: dict[int, str | None],
        *,
        reviewer: str,
        rationale: str,
    ) -> dict[str, Any]:
        """Record that one Ticket was replaced and another kept. An existing link is left as it is.

        A link that would close a loop (the kept Ticket already leads back to
        the replaced one through other links) is refused, because a loop
        would leave no Ticket kept.
        """
        if replaced_row == retained_row:
            raise ReviewError("same_ticket", "retained_row", "a ticket cannot replace itself")
        reviewer = clean_text("reviewer", reviewer, required=True)
        rationale = clean_text("rationale", rationale)
        numbers = [ticket_numbers.get(replaced_row), ticket_numbers.get(retained_row)]
        with self._lock:
            existing = {(link["replaced_row"], link["retained_row"]) for link in self._links(fingerprint)}
            if _leads_to(existing, retained_row, replaced_row):
                raise ReviewError(
                    "link_loop",
                    "replaced_row",
                    f"row {retained_row} is already recorded as replaced, directly or through other links, in favour of "
                    f"row {replaced_row}; this link would leave no ticket kept, so remove the other link first",
                    status=409,
                )
            changed = (replaced_row, retained_row) not in existing
            if changed:
                recorded_at = _now()
                with self._transaction():
                    self.connection.execute(
                        "INSERT INTO replacement_links VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        [fingerprint, replaced_row, retained_row, *numbers, reviewer, recorded_at, rationale],
                    )
                    self._append_history(
                        fingerprint, "link", [replaced_row, retained_row], numbers, reviewer, recorded_at,
                        None, _link_value(replaced_row, retained_row, numbers), rationale,
                    )
            link = self._link(fingerprint, replaced_row, retained_row)
        return {**link, "changed": changed}

    def unlink(self, fingerprint: str, replaced_row: int, retained_row: int, *, reviewer: str, rationale: str) -> dict[str, Any]:
        """Remove a link, keeping a history row of what it was."""
        reviewer = clean_text("reviewer", reviewer, required=True)
        rationale = clean_text("rationale", rationale)
        with self._lock:
            link = self._link(fingerprint, replaced_row, retained_row)
            if link is None:
                raise ReviewError(
                    "no_link", "replaced_row", f"no link records row {replaced_row} as replaced by row {retained_row}", status=404
                )
            numbers = [link["replaced_ticket_number"], link["retained_ticket_number"]]
            with self._transaction():
                self.connection.execute(
                    "DELETE FROM replacement_links WHERE snapshot_fingerprint = ? AND replaced_row = ? AND retained_row = ?",
                    [fingerprint, replaced_row, retained_row],
                )
                self._append_history(
                    fingerprint, "link", [replaced_row, retained_row], numbers, reviewer, _now(),
                    _link_value(replaced_row, retained_row, numbers), None, rationale,
                )
        return {**link, "removed": True}

    # Alias decisions

    def _alias_decisions(self, fingerprint: str) -> dict[tuple[str, str], dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT first_label, second_label, decision, reviewer, recorded_at, rationale FROM alias_decisions"
            " WHERE snapshot_fingerprint = ? ORDER BY first_label, second_label",
            [fingerprint],
        ).fetchall()
        return {
            (row[0], row[1]): {
                "decision": alias_decision_label(row[2]),
                "reviewer": row[3],
                "recorded_at": row[4],
                "rationale": row[5],
                "saved": True,
            }
            for row in rows
        }

    def confirmed_aliases(self, fingerprint: str) -> list[tuple[str, str]]:
        """The label pairs a reviewer confirmed for a Snapshot: what the rules widen the employee key by."""
        with self._lock:
            return [
                key for key, record in self._alias_decisions(fingerprint).items()
                if record["decision"]["id"] == "confirmed"
            ]

    def aliases(self, fingerprint: str, proposals: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        """Each proposal (labels, names, proposed_by) with its decision, Proposed until saved, and its history."""
        with self._lock:
            saved = self._alias_decisions(fingerprint)
            return [
                {
                    **proposal,
                    **(saved.get(tuple(proposal["labels"])) or _undecided()),
                    "history": self._history(fingerprint, kind="alias", labels=tuple(proposal["labels"])),
                }
                for proposal in proposals
            ]

    def save_alias(
        self,
        fingerprint: str,
        proposal: dict[str, Any],
        ticket_numbers: dict[int, str | None],
        *,
        decision: str,
        reviewer: str,
        rationale: str,
    ) -> dict[str, Any]:
        """Confirm or reject a proposed Alias; a change appends a history row.

        Every decision needs a rationale, because it changes which Tickets the
        rules compare. Saving the decision already saved changes nothing and
        appends no history. Returns the proposal with its decision, history and
        whether anything changed.
        """
        if decision not in SAVED_ALIAS_DECISIONS:
            raise ReviewError(
                "unknown_decision", "decision",
                f"{decision!r} is not an Alias decision; use one of {', '.join(SAVED_ALIAS_DECISIONS)}",
            )
        reviewer = clean_text("reviewer", reviewer, required=True)
        rationale = clean_text("rationale", rationale)
        labels = (proposal["labels"][0], proposal["labels"][1])
        # The history row names the Tickets proposing the Alias, so a drawer holding them lists it.
        rows = proposing_rows(proposal)
        with self._lock:
            previous = self._alias_decisions(fingerprint).get(labels)
            changed = previous is None or previous["decision"]["id"] != decision
            if changed and not rationale:
                raise ReviewError(
                    "rationale_required", "rationale",
                    "give a reason for this Alias decision; it changes which tickets the rules compare",
                )
            if changed:
                recorded_at = _now()
                with self._transaction():
                    self.connection.execute(
                        "INSERT OR REPLACE INTO alias_decisions VALUES (?, ?, ?, ?, ?, ?, ?)",
                        [fingerprint, *labels, decision, reviewer, recorded_at, rationale],
                    )
                    self._append_history(
                        fingerprint, "alias", rows, [ticket_numbers.get(row) for row in rows], reviewer, recorded_at,
                        None if previous is None else {"labels": list(labels), "decision": previous["decision"]},
                        {"labels": list(labels), "decision": alias_decision_label(decision)},
                        rationale, labels,
                    )
        [record] = self.aliases(fingerprint, [proposal])
        return {**record, "changed": changed}

    # History

    def _history(
        self,
        fingerprint: str,
        kind: str | None = None,
        excel_rows: list[int] | None = None,
        labels: tuple[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """History rows, newest first: the Snapshot's, or one subject's when kind and its rows or labels are given."""
        query = (
            "SELECT entry, kind, excel_rows, ticket_numbers, reviewer, recorded_at, previous_value, new_value, rationale,"
            " employee_labels FROM review_history WHERE snapshot_fingerprint = ?"
        )
        parameters: list[Any] = [fingerprint]
        if kind is not None and labels is not None:
            query += " AND kind = ? AND employee_labels = ?"
            parameters += [kind, list(labels)]
        elif kind is not None:
            query += " AND kind = ? AND excel_rows = ?"
            parameters += [kind, excel_rows]
        rows = self.connection.execute(query + " ORDER BY entry DESC", parameters).fetchall()
        return [
            {
                "entry": row[0],
                "kind": row[1],
                "excel_rows": list(row[2]),
                "ticket_numbers": list(row[3]),
                "reviewer": row[4],
                "recorded_at": row[5],
                "previous": json.loads(row[6]) if row[6] is not None else None,
                "new": json.loads(row[7]) if row[7] is not None else None,
                "rationale": row[8],
                **({"employee_labels": list(row[9])} if row[9] is not None else {}),
            }
            for row in rows
        ]

    def _append_history(
        self,
        fingerprint: str,
        kind: str,
        excel_rows: list[int],
        ticket_numbers: list[str | None],
        reviewer: str,
        recorded_at: str,
        previous: dict[str, Any] | None,
        new: dict[str, Any] | None,
        rationale: str,
        labels: tuple[str, str] | None = None,
    ) -> None:
        self.connection.execute(
            "INSERT INTO review_history (snapshot_fingerprint, kind, excel_rows, ticket_numbers, reviewer, recorded_at,"
            " previous_value, new_value, rationale, employee_labels) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                fingerprint, kind, excel_rows, ticket_numbers, reviewer, recorded_at,
                None if previous is None else json.dumps(previous),
                None if new is None else json.dumps(new),
                rationale,
                None if labels is None else list(labels),
            ],
        )

    # What the drawer and the ranked list read

    def for_possible_duplicate(
        self,
        fingerprint: str,
        pairs: list[dict[str, Any]],
        member_rows: list[int],
        proposals: Iterable[dict[str, Any]] = (),
    ) -> dict[str, Any]:
        """The review block of a possible duplicate's evidence.

        `pairs` are its Candidate pairs (excel_rows lower first, ticket
        numbers and rule IDs); each shows its saved outcome or Not reviewed.
        `proposals` are the Aliases about its members' labels, each shown with
        its decision. Links and history are those touching any member Ticket,
        plus the history of those Aliases.
        """
        with self._lock:
            saved = self._outcomes(fingerprint, [tuple(pair["excel_rows"]) for pair in pairs])
            links = self._links(fingerprint, member_rows)
            history = self._history(fingerprint)
            aliases = self.aliases(fingerprint, proposals)
        members = set(member_rows)
        alias_labels = {tuple(alias["labels"]) for alias in aliases}
        return {
            "outcome_values": [value.payload() for value in OUTCOME_VALUES],
            "alias_decision_values": [value.payload() for value in ALIAS_DECISION_VALUES],
            "aliases": aliases,
            "pairs": [
                {
                    **(saved.get(tuple(pair["excel_rows"])) or _unsaved(*pair["excel_rows"], pair["ticket_numbers"])),
                    "rule_ids": pair["rule_ids"],
                }
                for pair in pairs
            ],
            "links": links,
            "history": [
                entry for entry in history
                if members & set(entry["excel_rows"]) or tuple(entry.get("employee_labels", ())) in alias_labels
            ],
        }

    # Saved views (ticket #39). They are not review data: saving one leaves the review revision, and so the
    # Explore result cache, untouched.

    def saved_views(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.connection.execute(f"SELECT {VIEW_COLUMNS} FROM saved_views ORDER BY id").fetchall()
        return [_view(row) for row in rows]

    def saved_view(self, view_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self.connection.execute(f"SELECT {VIEW_COLUMNS} FROM saved_views WHERE id = ?", [view_id]).fetchone()
        return _view(row) if row else None

    def save_view(self, *, name: str, kind: str, state: dict[str, Any], saved_under: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        with self._lock:
            row = self.connection.execute(
                "INSERT INTO saved_views (name, kind, state, snapshot_fingerprint, as_of, versions, aliases, created_at,"
                f" updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING {VIEW_COLUMNS}",
                [
                    name, kind, json.dumps(state), saved_under["snapshot_fingerprint"], saved_under["as_of"],
                    json.dumps(saved_under["versions"]), json.dumps(saved_under["aliases"]), now, now,
                ],
            ).fetchone()
        return _view(row)

    def rename_view(self, view_id: int, name: str) -> dict[str, Any] | None:
        with self._lock:
            row = self.connection.execute(
                f"UPDATE saved_views SET name = ?, updated_at = ? WHERE id = ? RETURNING {VIEW_COLUMNS}",
                [name, _now(), view_id],
            ).fetchone()
        return _view(row) if row else None

    def delete_view(self, view_id: int) -> bool:
        with self._lock:
            row = self.connection.execute("DELETE FROM saved_views WHERE id = ? RETURNING id", [view_id]).fetchone()
        return row is not None

    def summary(self, fingerprint: str) -> dict[str, Any]:
        """Everything saved for a Snapshot: outcomes, links, the replaced Tickets, and the history."""
        with self._lock:
            outcomes = list(self._outcomes(fingerprint, None).values())
            links = self._links(fingerprint)
            history = self._history(fingerprint)
            aliases = [{"labels": list(key), **record} for key, record in self._alias_decisions(fingerprint).items()]
        return {
            "outcome_values": [value.payload() for value in OUTCOME_VALUES],
            "outcomes": outcomes,
            # Saved Alias decisions; a proposal nobody decided is not listed here (see the aliases request).
            "aliases": aliases,
            "links": links,
            # The only Tickets an adjusted figure may leave out: those an explicit link marks as replaced.
            "replaced_tickets": sorted({link["replaced_row"] for link in links}),
            "history": history,
            "store": {"path": str(self.path.resolve()), "file": REVIEW_FILE_NAME},
        }


def proposing_rows(proposal: dict[str, Any]) -> list[int]:
    """The Excel rows of every Ticket pair proposing an Alias, in order."""
    return sorted({row for pair in proposal["proposed_by"] for row in pair})


def alias_decision_label(decision_id: str) -> dict[str, str]:
    return {"id": decision_id, "label": ALIAS_DECISIONS[decision_id].label}


def _undecided() -> dict[str, Any]:
    return {"decision": alias_decision_label(PROPOSED.id), "reviewer": None, "recorded_at": None, "rationale": "", "saved": False}


def _unsaved(first_row: int, second_row: int, ticket_numbers: list[str | None]) -> dict[str, Any]:
    return {
        "excel_rows": [first_row, second_row],
        "ticket_numbers": ticket_numbers,
        "outcome": outcome_label(NOT_REVIEWED.id),
        "note": "",
        "reference": "",
        "reviewer": None,
        "recorded_at": None,
        "saved": False,
    }


def _leads_to(links: set[tuple[int, int]], start: int, target: int) -> bool:
    """Whether following replaced -> kept links from start reaches target (start itself counts)."""
    seen, frontier = set(), [start]
    while frontier:
        row = frontier.pop()
        if row == target:
            return True
        if row not in seen:
            seen.add(row)
            frontier.extend(retained for replaced, retained in links if replaced == row)
    return False


def _link_value(replaced_row: int, retained_row: int, numbers: list[str | None]) -> dict[str, Any]:
    return {
        "replaced_row": replaced_row,
        "retained_row": retained_row,
        "replaced_ticket_number": numbers[0],
        "retained_ticket_number": numbers[1],
    }


VIEW_COLUMNS = "id, name, kind, state, snapshot_fingerprint, as_of, versions, aliases, created_at, updated_at"


def _view(row: tuple) -> dict[str, Any]:
    view_id, name, kind, state, fingerprint, as_of, versions, aliases, created_at, updated_at = row
    return {
        "id": view_id,
        "name": name,
        "kind": kind,
        "state": json.loads(state),
        "saved_under": {
            "snapshot_fingerprint": fingerprint,
            "as_of": as_of,
            "versions": json.loads(versions),
            "aliases": json.loads(aliases),
        },
        "created_at": created_at,
        "updated_at": updated_at,
    }
