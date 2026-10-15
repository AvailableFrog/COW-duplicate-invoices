"""Read a Ticket's raw Time cell into work periods under the interval confidence policy.

The raw text is never altered: a parse result sits beside it and says what was
read, how confidently, and what was assumed. A period with explicit AM/PM or in
24-hour form is a Confident Interval. A period missing a meridiem is an
Ambiguous Interval carrying one Plausible Reading, always labelled assumed.
Reversed endpoints, implausible durations and possible overnight shifts are
flagged and never repaired. Intervals are half-open in minutes since midnight
of the Ticket's Date, so a period ending when another begins does not overlap.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

# Bump on any change to what a Time cell reads as.
PARSER_VERSION = "1.0.0"

NOON = 12 * 60
# A period this long or longer on one Date is flagged as implausible rather than read.
# In the export every such period is an AM/PM slip (7:30am-11:30pm claiming 4 hours),
# while genuine long days run to 15 hours (4:30am-7:30pm).
IMPLAUSIBLE_MINUTES = 16 * 60

Interval = tuple[int, int]
Status = Literal[
    "confident", "ambiguous", "flagged", "unrecognized", "blank",
    "zero_not_a_time", "number_not_a_time", "datetime_not_a_period", "not_time_text",
]
Confidence = Literal["confident", "ambiguous"]
Flag = Literal["reversed_endpoints", "possible_overnight", "implausible_duration"]
Meridiem = Literal["am", "pm", "noon"]

# One time as written. Alternatives are tried in order at each position.
MERIDIEM = r"(?:\s*(?P<meridiem>a\.?\s?m\.?|p\.?\s?m\.?|noon|a|p)(?![a-z]))?"
TIME = re.compile(
    r"(?:"
    r"(?P<hour>\d{1,2})\s*[:.;]\s*(?P<minute>\d{2})(?!\d)"  # 7:30, 7.30, 7;30, 7 :30
    r"|(?P<slash_hour>\d{1,2})/(?P<slash_minute>\d{2})(?=\s*[ap])"  # 7/30am; a slash before a meridiem only
    r"|(?P<compact>\d{3,4})(?!\d)"  # 730, 1030, 0730
    r"|(?P<spaced_hour>\d{1,2})\s+(?P<spaced_minute>00|1[3-9]|[2-5]\d)(?![\d:.;/])"  # 7 30
    r"|(?P<bare_hour>\d{1,2})(?!\d)"  # 7
    r")" + MERIDIEM,
    re.IGNORECASE | re.ASCII,
)
# What may sit between, before or after times: range connectors and period separators.
CONNECTOR = re.compile(
    r"(?:\s|[-‐-―_/&,+.:;]|to(?![a-z])|till(?![a-z])|until(?![a-z])|and(?![a-z]))+",
    re.IGNORECASE | re.ASCII,
)

STATUS_NOTES: dict[Status, str] = {
    "confident": "Every period has explicit AM/PM or is in 24-hour form.",
    "ambiguous": "At least one period lacks AM/PM; its Plausible Reading is assumed and cannot prove overlap or separation.",
    "flagged": "At least one period is reversed, implausibly long or possibly overnight; it is flagged and not repaired.",
    "unrecognized": "The Time text could not be read as work periods; it is kept as written.",
    "blank": "The Time cell is empty.",
    "zero_not_a_time": "The Time cell holds the number 0: zero, not a time, and never midnight.",
    "number_not_a_time": "The Time cell holds a number, not time text; it is not read as a time.",
    "datetime_not_a_period": "The Time cell holds a date and time value, a single moment rather than a work period; it is not read as one.",
    "not_time_text": "The Time cell holds neither text nor a number; it is not read as a time.",
}


@dataclass(frozen=True)
class Clock:
    """One time as written: hour and minute, its meridiem if any, and whether it is in 24-hour form."""

    text: str
    text_start: int  # character offsets of the time in the cell text
    text_end: int
    hour: int
    minute: int
    meridiem: Meridiem | None
    twenty_four_hour: bool  # hour 0 or 13-23, or written with a leading zero

    @property
    def explicit(self) -> bool:
        return self.meridiem is not None or self.twenty_four_hour

    def minutes(self) -> int:
        """Minutes since midnight; only meaningful when the time needs no assumption."""
        if self.meridiem == "noon":
            return NOON
        if self.meridiem == "am":
            return (self.hour % 12) * 60 + self.minute
        if self.meridiem == "pm":
            return (self.hour % 12 + 12) * 60 + self.minute
        return self.hour * 60 + self.minute

    def label(self) -> str:
        return f"{self.hour}:{self.minute:02d}"


@dataclass(frozen=True)
class Period:
    text: str
    confidence: Confidence
    interval: Interval | None
    plausible_reading: Interval | None
    flags: tuple[Flag, ...]
    notes: tuple[str, ...]

    def payload(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "confidence": self.confidence,
            "interval": _interval_payload(self.interval),
            "plausible_reading": (
                None if self.plausible_reading is None else {**_interval_payload(self.plausible_reading), "assumed": True}
            ),
            "flags": list(self.flags),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class TimeParse:
    raw_type: str
    raw_value: Any
    status: Status
    periods: tuple[Period, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def has_ambiguous_interval(self) -> bool:
        """Whether any period lacks AM/PM: an Ambiguous Interval, flagged or not."""
        return any(period.confidence == "ambiguous" for period in self.periods)

    def confident_intervals(self) -> list[Interval]:
        """The union of this Ticket's Confident Intervals, merged and in order."""
        return _union(period.interval for period in self.periods if period.interval is not None)

    def payload(self) -> dict[str, Any]:
        return {
            "raw_time": {"raw_type": self.raw_type, "value": self.raw_value},
            "parser_version": PARSER_VERSION,
            "status": self.status,
            "periods": [period.payload() for period in self.periods],
            "confident_union": [_interval_payload(interval) for interval in self.confident_intervals()],
            "notes": [STATUS_NOTES[self.status], *self.notes],
        }


def parse_time(raw_type: str, value: Any) -> TimeParse:
    """Classify and read one Time cell, typed or text, without ever raising."""
    if raw_type == "blank" or (raw_type == "str" and not str(value).strip()):
        return TimeParse(raw_type, value, "blank")
    if raw_type in ("int", "float"):
        return TimeParse(raw_type, value, "zero_not_a_time" if value == 0 else "number_not_a_time")
    if raw_type == "datetime":
        return TimeParse(raw_type, value, "datetime_not_a_period")
    if raw_type != "str":
        return TimeParse(raw_type, value, "not_time_text")
    return _parse_text(value)


def compare(first: TimeParse, second: TimeParse) -> dict[str, Any]:
    """Whether two Tickets' work periods overlap, comparing the union of their intervals.

    Only Confident Intervals establish overlap or separation. When either
    Ticket has an Ambiguous Interval and no confident overlap exists, the
    result is "ambiguous" and the Plausible Readings are compared, labelled
    assumed. A Ticket with a flagged or unread period, or no periods at all,
    leaves the comparison "undetermined" unless confident overlap exists.
    """
    intersection = _intersect(first.confident_intervals(), second.confident_intervals())
    if intersection:
        return _comparison("overlap", "confident_intervals", intersection)
    if first.status == second.status == "confident":
        return _comparison("separate", "confident_intervals", [])
    if all(parse.status in ("confident", "ambiguous") for parse in (first, second)):
        return _comparison("ambiguous", "plausible_readings", _intersect(_readings(first), _readings(second)))
    return _comparison("undetermined", None, [])


COMPARISON_EXPLANATIONS = {
    "overlap": "Confident Intervals intersect, so the work periods overlap.",
    "separate": "Every period on both Tickets is a Confident Interval and their unions do not intersect.",
    "ambiguous": (
        "At least one period lacks AM/PM, so overlap or separation cannot be established. "
        "The Plausible Readings are compared instead; the result is assumed."
    ),
    "undetermined": "At least one Ticket has no readable, unflagged work period, so the times cannot be compared.",
}


def _comparison(result: str, basis: str | None, intersection: list[Interval]) -> dict[str, Any]:
    return {
        "result": result,
        "basis": basis,
        "assumed": basis == "plausible_readings",
        "intersection": [_interval_payload(interval) for interval in intersection],
        "overlap_minutes": sum(end - start for start, end in intersection),
        "explanation": COMPARISON_EXPLANATIONS[result],
    }


def _readings(parse: TimeParse) -> list[Interval]:
    """Confident Intervals together with Plausible Readings: the assumed picture of a Ticket's work."""
    return _union(
        period.interval or period.plausible_reading
        for period in parse.periods
        if (period.interval or period.plausible_reading) is not None
    )


def _intersect(first: list[Interval], second: list[Interval]) -> list[Interval]:
    """Positive-length intersections of two merged interval lists; touching ends do not count."""
    overlaps = []
    for a_start, a_end in first:
        for b_start, b_end in second:
            start, end = max(a_start, b_start), min(a_end, b_end)
            if start < end:
                overlaps.append((start, end))
    return _union(overlaps)


def _parse_text(text: str) -> TimeParse:
    clocks, problem = _scan(text)
    if problem is None and not clocks:
        problem = "No times were found."
    if problem is None and len(clocks) % 2:
        count = len(clocks)
        problem = f"Found {count} {'time' if count == 1 else 'times'}, which cannot be paired into start and end times."
    if problem is not None:
        return TimeParse("str", text, "unrecognized", notes=(problem,))
    periods = tuple(_period(text, clocks[i], clocks[i + 1]) for i in range(0, len(clocks), 2))
    if any(period.flags for period in periods):
        status = "flagged"
    elif any(period.confidence == "ambiguous" for period in periods):
        status = "ambiguous"
    else:
        status = "confident"
    return TimeParse("str", text, status, periods)


def _scan(text: str) -> tuple[list[Clock], str | None]:
    """Every time in the text in order, or a note naming what could not be read."""
    clocks: list[Clock] = []
    position = 0
    while position < len(text):
        connector = CONNECTOR.match(text, position)
        if connector and connector.end() > position:
            position = connector.end()
            continue
        match = TIME.match(text, position)
        if match is None:
            rest = text[position:].strip()
            return clocks, f"Could not read {rest!r}."
        clock = _clock(match)
        if clock is None:
            return clocks, f"{match.group(0).strip()!r} is not a time of day."
        clocks.append(clock)
        position = match.end()
    return clocks, None


def _clock(match: re.Match[str]) -> Clock | None:
    groups = match.groupdict()
    if groups["compact"] is not None:
        hour_text, minute_text = groups["compact"][:-2], groups["compact"][-2:]
    else:
        hour_text = groups["hour"] or groups["slash_hour"] or groups["spaced_hour"] or groups["bare_hour"]
        minute_text = groups["minute"] or groups["slash_minute"] or groups["spaced_minute"] or "00"
    hour, minute = int(hour_text), int(minute_text)
    meridiem = _meridiem(groups["meridiem"])
    if minute > 59:
        return None
    if meridiem == "noon":
        if (hour, minute) != (12, 0):
            return None
    elif meridiem is not None:
        if not 1 <= hour <= 12:
            return None
    elif hour > 23:
        return None
    twenty_four_hour = meridiem is None and (hour == 0 or hour >= 13 or (len(hour_text) == 2 and hour_text[0] == "0"))
    return Clock(match.group(0).strip(), match.start(), match.end(), hour, minute, meridiem, twenty_four_hour)


def _meridiem(text: str | None) -> Meridiem | None:
    if text is None:
        return None
    letters = re.sub(r"[^a-z]", "", text.lower())
    if letters == "noon":
        return "noon"
    return "am" if letters.startswith("a") else "pm"


def _period(text: str, start: Clock, end: Clock) -> Period:
    span = text[start.text_start:end.text_end].strip()
    in_24_hour_form = start.meridiem is None and end.meridiem is None and (start.twenty_four_hour or end.twenty_four_hour)
    if in_24_hour_form or (start.explicit and end.explicit):
        # In 24-hour form one end can only be on the 24-hour clock, so both are read on it.
        return _confident(span, start.minutes(), end.minutes())
    return _ambiguous(span, start, end)


def _confident(span: str, start: int, end: int) -> Period:
    flags, notes = _flags(start, end)
    return Period(span, "confident", None if flags else (start, end), None, flags, notes)


def _ambiguous(span: str, start: Clock, end: Clock) -> Period:
    """An Ambiguous Interval and its one Plausible Reading under the working-day interpretation.

    A start from 5:00 to 11:59 is taken as AM and one from 12:00 to 4:59 as
    afternoon; an end is taken as the first reading at or after the start, so an
    end numerically below the start is PM and an end equal to it is zero length.
    A known endpoint fixes the other.
    """
    unmarked = " and ".join(clock.label() for clock in (start, end) if not clock.explicit)
    notes = [f"No AM/PM on {unmarked}, so this period cannot prove overlap or separation."]
    if start.explicit:
        start_minutes = start.minutes()
    elif end.explicit:
        before = [minutes for minutes in _half_days(start) if minutes <= end.minutes()]
        if not before:
            return _overnight_without_reading(span, notes)
        start_minutes = before[-1]
        notes.append(f"Assumed: {start.label()} is {_half_day(start_minutes)}, to fall before the end.")
    else:
        morning, afternoon = _half_days(start)
        start_minutes = morning if 5 <= start.hour <= 11 else afternoon
        notes.append(
            f"Assumed: {start.label()} is {_half_day(start_minutes)}; a start from 5:00 to 11:59 is read as AM"
            " and one from 12:00 to 4:59 as afternoon."
        )
    if end.explicit:
        end_minutes = end.minutes()
    else:
        after = [minutes for minutes in _half_days(end) if minutes >= start_minutes]
        if not after:
            return _overnight_without_reading(span, notes)
        end_minutes = after[0]
        notes.append(f"Assumed: {end.label()} is {_half_day(end_minutes)}, the first reading at or after the start.")
    flags, flag_notes = _flags(start_minutes, end_minutes)
    reading = None if flags else (start_minutes, end_minutes)
    return Period(span, "ambiguous", None, reading, flags, (*notes, *flag_notes))


def _overnight_without_reading(span: str, notes: list[str]) -> Period:
    """No reading puts the end after the start on one Date: flagged, never repaired."""
    note = "No reading puts the end after the start on the same Date; possibly an overnight shift. Not repaired."
    return Period(span, "ambiguous", None, None, ("possible_overnight",), (*notes, note))


def _half_days(clock: Clock) -> tuple[int, int]:
    """The AM and PM readings of a time written without a meridiem, in minutes since midnight."""
    morning = (clock.hour % 12) * 60 + clock.minute
    return morning, morning + NOON


def _half_day(minutes: int) -> str:
    return "AM" if minutes < NOON else "PM"


def _flags(start: int, end: int) -> tuple[tuple[Flag, ...], tuple[str, ...]]:
    """Flags for a read period; a flagged period gets no interval or reading."""
    if end < start:
        if start >= NOON and end < NOON:
            return ("possible_overnight",), ("Ends before it starts on the clock; possibly an overnight shift. Not repaired.",)
        return ("reversed_endpoints",), ("Ends before it starts. Not repaired.",)
    if end == start or end - start >= IMPLAUSIBLE_MINUTES:
        hours = (end - start) / 60
        return ("implausible_duration",), (f"Lasts {hours:g} hours on one Date, which is implausible. Not repaired.",)
    return (), ()


def _union(intervals) -> list[Interval]:
    merged: list[Interval] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _interval_payload(interval: Interval | None) -> dict[str, str] | None:
    if interval is None:
        return None
    return {"start": _hhmm(interval[0]), "end": _hhmm(interval[1])}


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"
