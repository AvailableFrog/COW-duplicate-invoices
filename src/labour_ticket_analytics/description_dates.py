"""The Description-date exception: explicit service dates written in a description, compared with Date.

A Ticket-level exception, never a matching rule: it reads one Ticket's
"Description of Job Work" text, finds explicit date references and says
whether any of them differs from the Ticket's Date. It never creates a
Candidate, never links two Tickets and never changes Date; the recorded Date
stays the Ticket's Date and the description is review evidence (PRD section 5).

It runs once at import, beside the Time parse, and is versioned with the
matching rules (RULE_VERSION), so a change here bumps that version.

Recognised references, case-insensitive (decision-log entry 68):

- ISO dates: ``2026-09-12``.
- A day with a month name, the year optional: ``12 September``, ``12th September 2026``,
  ``9th of September``, ``11 th September``, ``4 Sep 26``, ``Sept 12``, ``September 12th, 2026``.
  Month names are written in full or as ``Jan``, ``Feb``, ``Mar``, ``Apr``, ``Jun``, ``Jul``,
  ``Aug``, ``Sep``, ``Sept``, ``Oct``, ``Nov`` or ``Dec``, with or without a full stop.
- Numbers with slashes: ``12/09``, ``12/09/2026``, ``12/09/26``. When both numbers could be the
  month, the reference carries both readings (day/month and month/day) and is uncertain; the order
  is never chosen. When only one order is a calendar date, that order is read and the note says why.
  A slash time such as ``7/30am`` is not a date.
- Ranges joined by ``to``, ``till``, ``until``, ``through``, ``thru`` or a dash, where one end may
  give only an ordinal day and borrow the other end's month and year: ``2nd to 8th Sep``,
  ``Sep 2nd to the 10th``, ``11 th September -22nd September``, ``2026-10-09 to 2026-10-29``.

Anything else is not a date reference: an ordinal day with no month (``the 10th``), a month name
with no day, or numbers with dots or colons, which in descriptions are amounts and times.
The text is never interpreted beyond the date itself: a vacation's return date is a date reference
like any other, since semantic reading of descriptions is deferred (PRD section 5).

A reference with no year written is compared in the year of Date and flagged uncertain
(``year_omitted``); a two-digit year is read as 20YY and flagged (``two_digit_year``); an
unresolved day/month order is flagged (``day_month_order``). A reference differs from Date when
Date falls in none of its readings (a range reads as every day from its start to its end).
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Any, Literal

from labour_ticket_analytics.rules import RULE_VERSION, SERVICE_DATE_IN_DESCRIPTION

CHECK_ID = "description_date_exception"
DESCRIPTION_FIELD = "Description of Job Work"

Status = Literal["conflict", "agrees", "no_date_reference", "blank", "not_text", "date_unusable", "disabled"]
Uncertainty = Literal["year_omitted", "two_digit_year", "day_month_order"]

STATUS_NOTES: dict[Status, str] = {
    "conflict": "The description names a date that differs from Date. Date is kept as recorded; the description never changes it.",
    "agrees": "Every date the description names agrees with Date.",
    "no_date_reference": "The description names no explicit date.",
    "blank": "The description is empty.",
    "not_text": "The description cell is not text, so no date is read from it.",
    "date_unusable": "Date is missing or not a date, so the description's dates cannot be compared with it.",
    "disabled": "The workbook has no Description of Job Work column, so service dates written in descriptions cannot be compared with Date.",
}
UNCERTAINTY_NOTES: dict[Uncertainty, str] = {
    "year_omitted": "No year is written; compared in the year of Date, which is an assumption.",
    "two_digit_year": "The year is written with two digits and read as 20YY, which is an assumption.",
    "day_month_order": "Day and month could be either way round, so both readings are kept and neither is chosen.",
}

MONTHS: dict[str, int] = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4, "may": 5,
    "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November",
    "December",
)

_MONTH = (
    r"(?P<{name}>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?(?![a-z])"
)
_ORDINAL = r"(?:\s?(?:st|nd|rd|th)(?![a-z]))"
# One date atom; alternatives are tried in order at each position, the leftmost match wins.
ATOM = re.compile(
    r"(?P<iso>(?<![\d/.-])(?P<iso_year>\d{4})-(?P<iso_month>\d{1,2})-(?P<iso_day>\d{1,2})(?![\d-]))"
    # 12 September 2026, 9th of September, 4 Sep 26
    r"|(?P<day_month>(?<![\d.,:/$£])(?P<dm_day>\d{1,2})" + _ORDINAL + r"?\s*(?:of\s+)?"
    + _MONTH.format(name="dm_month")
    + r"(?:,?\s*(?P<dm_year>\d{4}|\d{2})(?![\d:/]|[.,]\d|\s?(?:st|nd|rd|th|am|pm|hrs?|hours?|days?)(?![a-z])))?)"
    # Sept 12, September 12th, 2026
    r"|(?P<month_day>" + _MONTH.format(name="md_month")
    + r"\s*(?P<md_day>\d{1,2})" + _ORDINAL + r"?(?![\d:/]|[.,]\d)(?:,?\s*(?P<md_year>\d{4})(?!\d))?)"
    # 12/09, 12/09/2026; never a time such as 7/30am or a fraction such as 1/2 day
    r"|(?P<numeric>(?<![\d/.:$£])(?P<num_first>\d{1,2})/(?P<num_second>\d{1,2})"
    r"(?:/(?P<num_year>\d{4}|\d{2}))?(?![\d/:])(?!\s*(?:[ap](?:\.?m)?|days?|hrs?|hours?)(?![a-z])))"
    # an ordinal day alone (the 10th): only a date as one end of a range with a month
    r"|(?P<ordinal>(?<![\d.,:/$£])(?P<ord_day>\d{1,2})" + _ORDINAL + r")",
    re.IGNORECASE,
)
RANGE_CONNECTOR = re.compile(r"\s*(?:-|–|—|to|till|until|through|thru)\s*(?:the\s+)?", re.IGNORECASE)


@dataclass(frozen=True)
class _Atom:
    """One date as written; `month` None for an ordinal day alone, `readings` its (day, month) orders."""

    start: int
    end: int
    kind: str  # iso, day_month, month_day, numeric, ordinal
    readings: tuple[tuple[int, int], ...]  # (day, month) pairs; empty for an ordinal day alone
    day: int | None
    year: int | None
    two_digit_year: bool = False
    order_note: str | None = None


@dataclass(frozen=True)
class DateReference:
    """An explicit date reference in a description: its text span, how it reads and whether it differs from Date."""

    text: str
    start: int  # character offsets in the description text
    end: int
    kind: Literal["date", "range"]
    interpretation: str
    readings: tuple[tuple[dt.date, dt.date], ...]  # each an inclusive span; a single date starts and ends on itself
    year_written: bool
    uncertainty: tuple[Uncertainty, ...]
    notes: tuple[str, ...]
    differs_from_date: bool | None  # None when Date is unusable

    def payload(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "start": self.start,
            "end": self.end,
            "kind": self.kind,
            "interpretation": self.interpretation,
            "readings": [{"from": first.isoformat(), "to": last.isoformat()} for first, last in self.readings],
            "year_written": self.year_written,
            "uncertain": bool(self.uncertainty),
            "uncertainty": list(self.uncertainty),
            "notes": list(self.notes),
            "differs_from_date": self.differs_from_date,
        }


@dataclass(frozen=True)
class DescriptionDates:
    """One Ticket's Description-date exception result."""

    status: Status
    date: dt.date | None
    references: tuple[DateReference, ...] = ()

    @property
    def conflict(self) -> bool:
        return self.status == "conflict"

    def payload(self) -> dict[str, Any]:
        differing = [reference for reference in self.references if reference.differs_from_date]
        return {
            "check": CHECK_ID,
            "pattern": SERVICE_DATE_IN_DESCRIPTION.payload(),
            "rule_version": RULE_VERSION,
            "status": self.status,
            "conflict": self.conflict,
            "uncertain": any(reference.uncertainty for reference in differing),
            "date": self.date.isoformat() if self.date else None,
            "references": [reference.payload() for reference in self.references],
            "note": STATUS_NOTES[self.status],
        }


def check(raw_type: str | None, value: Any, date: dt.date | None) -> DescriptionDates:
    """The exception for one Ticket: `raw_type` and `value` are its description cell (None when the column is
    absent) and `date` the calendar date of its Date, or None when Date is unusable."""
    if raw_type is None:
        return DescriptionDates("disabled", date)
    if raw_type == "blank" or (raw_type == "str" and not value.strip()):
        return DescriptionDates("blank", date)
    if raw_type != "str":
        return DescriptionDates("not_text", date)
    references = tuple(find_references(value, date))
    if not references:
        return DescriptionDates("no_date_reference", date)
    if date is None:
        return DescriptionDates("date_unusable", date, references)
    status: Status = "conflict" if any(reference.differs_from_date for reference in references) else "agrees"
    return DescriptionDates(status, date, references)


def find_references(text: str, date: dt.date | None) -> list[DateReference]:
    """Every explicit date reference in `text`, in order; a year left out is read in `date`'s year."""
    atoms = [atom for match in ATOM.finditer(text) if (atom := _atom(match)) is not None]
    references: list[DateReference] = []
    index = 0
    while index < len(atoms):
        atom = atoms[index]
        following = atoms[index + 1] if index + 1 < len(atoms) else None
        if following is not None and _joined(text, atom, following):
            reference = _range(text, atom, following, date)
            if reference is not None:
                references.append(reference)
                index += 2
                continue
        if atom.kind != "ordinal":
            reference = _single(text, atom, date)
            if reference is not None:
                references.append(reference)
        index += 1
    return references


def _atom(match: re.Match[str]) -> _Atom | None:
    groups = match.groupdict()
    kind = next(name for name in ("iso", "day_month", "month_day", "numeric", "ordinal") if groups[name] is not None)
    start, end = match.span(kind)
    if kind == "iso":
        return _valid(_Atom(start, end, kind, ((int(groups["iso_day"]), int(groups["iso_month"])),), None,
                            int(groups["iso_year"])))
    if kind in ("day_month", "month_day"):
        prefix = "dm" if kind == "day_month" else "md"
        year_text = groups[f"{prefix}_year"]
        day = int(groups[f"{prefix}_day"])
        month = MONTHS[groups[f"{prefix}_month"].casefold()]
        year, two_digit = _year(year_text)
        return _valid(_Atom(start, end, kind, ((day, month),), None, year, two_digit))
    if kind == "numeric":
        first, second = int(groups["num_first"]), int(groups["num_second"])
        year, two_digit = _year(groups["num_year"])
        orders = []
        if 1 <= second <= 12:
            orders.append((first, second))  # day/month
        if 1 <= first <= 12 and first != second:
            orders.append((second, first))  # month/day
        note = None
        if len(orders) == 1 and first != second:
            day, month = orders[0]
            note = (
                f"Read as day/month: {first} cannot be a month." if (day, month) == (first, second)
                else f"Read as month/day: {second} cannot be a month."
            )
        return _valid(_Atom(start, end, kind, tuple(orders), None, year, two_digit, note))
    return _Atom(start, end, kind, (), int(groups["ord_day"]), None)


def _year(text: str | None) -> tuple[int | None, bool]:
    if text is None:
        return None, False
    return (2000 + int(text), True) if len(text) == 2 else (int(text), False)


def _valid(atom: _Atom) -> _Atom | None:
    """The atom keeping only readings that are calendar dates (in a leap year when no year is written); None if none is."""
    year = atom.year if atom.year is not None else 2024
    readings = tuple(reading for reading in atom.readings if _calendar(year, reading[1], reading[0]) is not None)
    if not readings:
        return None
    return _Atom(atom.start, atom.end, atom.kind, readings, atom.day, atom.year, atom.two_digit_year, atom.order_note)


def _calendar(year: int, month: int, day: int) -> dt.date | None:
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


def _joined(text: str, first: _Atom, second: _Atom) -> bool:
    """Whether two atoms are the two ends of one range: only a range connector between them."""
    between = text[first.end:second.start]
    return RANGE_CONNECTOR.fullmatch(between) is not None and "numeric" not in (first.kind, second.kind)


def _range(text: str, first: _Atom, second: _Atom, date: dt.date | None) -> DateReference | None:
    """A range of two atoms, an ordinal end borrowing the other end's month and year; None when it does not read."""
    if first.kind == "ordinal" and second.kind == "ordinal":
        return None
    if first.kind == "ordinal":
        (_, month), = second.readings
        first = _Atom(first.start, first.end, "day_month", ((first.day, month),), None, second.year, second.two_digit_year)
    elif second.kind == "ordinal":
        (_, month), = first.readings
        second = _Atom(second.start, second.end, "day_month", ((second.day, month),), None, first.year, first.two_digit_year)
    start = _resolve(first, date)
    end = _resolve(second, date)
    if not start or not end:
        return None
    (start_day,), (end_day,) = start, end
    if start_day > end_day:
        return None
    uncertainty = _uncertainty(first, second)
    return DateReference(
        text=text[first.start:second.end],
        start=first.start,
        end=second.end,
        kind="range",
        interpretation=_spoken((start_day, end_day), " to ", first.year is not None and second.year is not None),
        readings=((start_day, end_day),),
        year_written=first.year is not None and second.year is not None,
        uncertainty=uncertainty,
        notes=tuple(UNCERTAINTY_NOTES[item] for item in uncertainty),
        differs_from_date=None if date is None else not start_day <= date <= end_day,
    )


def _single(text: str, atom: _Atom, date: dt.date | None) -> DateReference | None:
    days = _resolve(atom, date)
    if not days:
        return None
    uncertainty = _uncertainty(atom)
    notes = [UNCERTAINTY_NOTES[item] for item in uncertainty]
    if atom.order_note:
        notes.append(atom.order_note)
    return DateReference(
        text=text[atom.start:atom.end],
        start=atom.start,
        end=atom.end,
        kind="date",
        interpretation=_spoken(days, " or ", atom.year is not None),
        readings=tuple((day, day) for day in days),
        year_written=atom.year is not None,
        uncertainty=uncertainty,
        notes=tuple(notes),
        differs_from_date=None if date is None else date not in days,
    )


def _resolve(atom: _Atom, date: dt.date | None) -> tuple[dt.date, ...]:
    """The atom's calendar dates; a year left out is Date's year (a leap year when Date is unusable, since such a
    reference is then only shown in words and never compared)."""
    year = atom.year if atom.year is not None else (date.year if date is not None else 2024)
    return tuple(day for day in (_calendar(year, month, day) for day, month in atom.readings) if day is not None)


def _uncertainty(*atoms: _Atom) -> tuple[Uncertainty, ...]:
    found: list[Uncertainty] = []
    if any(atom.year is None for atom in atoms):
        found.append("year_omitted")
    if any(atom.two_digit_year for atom in atoms):
        found.append("two_digit_year")
    if any(len(atom.readings) > 1 for atom in atoms):
        found.append("day_month_order")
    return tuple(found)


def _spoken(days: tuple[dt.date, ...], joiner: str, year_written: bool) -> str:
    """Dates in words, with years only when written: "9 September 2026", "2 to 8 September (no year written)"."""
    if not year_written:
        words = [f"{day.day} {MONTH_NAMES[day.month - 1]}" for day in days]
        if joiner == " to " and days[0].month == days[-1].month:
            words[0] = str(days[0].day)
        return joiner.join(words) + " (no year written)"
    return joiner.join(f"{day.day} {MONTH_NAMES[day.month - 1]} {day.year}" for day in days)
