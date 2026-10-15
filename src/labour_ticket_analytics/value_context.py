"""The value-context panel: three small BBD figures giving the scale of recorded claims, never the headline.

Each figure is one registry metric (PRD section 9), evaluated under the
active filters, and carries its formula, interpretation and a completeness
note computed from the metric's coverage:

1. Known base-value components (`known_base_value_bbd`) over every Ticket.
2. Base value of the flagged duplicates (`flagged_duplicate_base_value_bbd`).
3. One extra claim per exact repeat, not flagged
   (`unflagged_exact_repeat_extra_claim_bbd`): a hypothetical n - 1 count
   valid only for strict groups (PRD section 5).

The flagged and unflagged scenarios overlap and are never added together.
Unpriced labour is disclosed beside the figures, never valued at zero. Only
explicit kept/replaced links can produce an adjusted figure: when any exist,
the panel offers `reviewed_known_base_value_bbd` as a separately labelled
analyst-reviewed alternative; a Review Outcome or note alone changes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable

from labour_ticket_analytics.annotations import ANNOTATIONS

CURRENCY = "BBD"
TITLE = "Value context"
NOTE = (
    "Three figures in Barbados dollars (BBD) giving the scale of recorded claims. Each answers a different question "
    "about tickets that overlap, so they are never added together: the flagged duplicates and the exact repeats, not "
    "flagged, are separate scenarios. The export holds no payment records, so no figure is an amount disbursed, "
    "avoided or owed."
)


@dataclass(frozen=True)
class Figure:
    id: str
    metric_id: str
    scenario: str
    formula: str
    interpretation: str


KNOWN = Figure(
    "known_base_value", "known_base_value_bbd", "recorded",
    formula=(
        "Per ticket: Rate × (Regular Hours + Overtime + Double Time) + Job Work Pay, rounded half-up to cents; then "
        "summed over every ticket, Rejected ones included. Hours are taken at the recorded Rate, with no overtime or "
        "double-time multipliers."
    ),
    interpretation=(
        "A partial valuation of what the tickets claim, including Rejected tickets and any repeats as recorded. It is "
        "not a total disbursed or owed: the export holds no payment records."
    ),
)
FLAGGED = Figure(
    "flagged_duplicates", "flagged_duplicate_base_value_bbd", "flagged",
    formula="The same per-ticket base value, summed over the flagged duplicates: tickets Approved with Job Number 0.",
    interpretation=(
        "The value of the tickets staff flagged as duplicates. It is not a verified reduction in cost: the export "
        "cannot show whether any of them would otherwise have been disbursed."
    ),
)
EXTRA_CLAIM = Figure(
    "extra_claim_per_exact_repeat", "unflagged_exact_repeat_extra_claim_bbd", "hypothetical",
    formula=(
        "For each exact repeat, not flagged, with n tickets: their per-ticket base values summed, less the highest "
        "one (the claim taken as kept), so n − 1 whole claims; then summed over the exact repeats."
    ),
    interpretation=(
        "Hypothetical: the value of one whole claim per exact repeat, not flagged, if one claim in each were "
        "unnecessary. It is not a confirmed excess; whether staff handled these somewhere the export cannot show is a "
        "question for Oliver."
    ),
)
FIGURES = (KNOWN, FLAGGED, EXTRA_CLAIM)
REVIEWED = Figure(
    "reviewed_known_base_value", "reviewed_known_base_value_bbd", "analyst_reviewed",
    formula=(
        "The known base-value components, leaving out each ticket a reviewer linked as replaced by a kept ticket."
    ),
    interpretation=(
        "An analyst's alternative to the first figure, not a correction of the source: only an explicit kept/replaced "
        "link leaves a ticket out, and a Review Outcome or note alone never does. The recorded figure stays as it is."
    ),
)

# Approval statuses of a set of Tickets, most first, as the store counts them.
StatusCounts = Callable[[list[int]], list[dict[str, Any]]]


def panel(
    results: dict[str, dict[str, Any]],
    reviewed: dict[str, Any] | None,
    replaced_rows: list[int],
    status_counts: StatusCounts,
) -> dict[str, Any]:
    """The panel from its evaluated registry metrics, keyed by metric ID.

    `reviewed` is the analyst-reviewed metric's result, evaluated with
    `replaced_rows`; it is shown only when some link marks a Ticket replaced.
    """
    known = results[KNOWN.metric_id]
    unpriced = _unpriced(known, status_counts)
    figures = [
        _figure(KNOWN, known, _known_completeness(known, unpriced)),
        _figure(FLAGGED, results[FLAGGED.metric_id], _flagged_completeness(results[FLAGGED.metric_id], status_counts)),
        _extra_claim_figure(results[EXTRA_CLAIM.metric_id]),
    ]
    alternative = None
    if replaced_rows and reviewed is not None:
        alternative = _reviewed_alternative(known, reviewed, replaced_rows, status_counts)
    return {
        "title": TITLE,
        "currency": CURRENCY,
        "note": NOTE,
        "figures": figures,
        "unpriced_labour": unpriced,
        "reviewed_alternative": alternative,
    }


def _figure(figure: Figure, result: dict[str, Any], completeness: str) -> dict[str, Any]:
    coverage = result["coverage"] or {"contributing_tickets": 0, "excluded": [], "partial": []}
    return {
        "id": figure.id,
        "metric_id": figure.metric_id,
        "label": result["metric"]["label"],
        "scenario": figure.scenario,
        "value": result["value"],
        "currency": CURRENCY,
        "formula": figure.formula,
        "interpretation": figure.interpretation,
        "completeness": completeness,
        "definition": result["metric"]["definition"],
        "grain": result["grain"],
        "tickets": result.get("tickets", coverage["contributing_tickets"]),
        "availability": result["availability"],
        "coverage": result["coverage"],
        "warnings": result["warnings"],
    }


def _partial(result: dict[str, Any], code: str) -> dict[str, Any] | None:
    coverage = result["coverage"] or {"partial": []}
    return next((item for item in coverage["partial"] if item["code"] == code), None)


def _unpriced(result: dict[str, Any], status_counts: StatusCounts) -> dict[str, Any]:
    """The labour a base-value metric could not price: Tickets, hours, their statuses and rows."""
    item = _partial(result, "unpriced_labour")
    rows = list(item["excel_rows"]) if item else []
    return {
        "tickets": item["tickets"] if item else 0,
        "hours": item["quantity"] if item else 0,
        "statuses": status_counts(rows),
        "excel_rows": rows,
    }


def _known_completeness(result: dict[str, Any], unpriced: dict[str, Any]) -> str:
    if result["availability"]["status"] != "available":
        return result["availability"]["reason"]
    parts = [f"{_count(result['coverage']['contributing_tickets'], 'ticket')} contribute."]
    if unpriced["tickets"]:
        parts.append(
            f"{_tickets_with_status(unpriced)} {'claims' if unpriced['tickets'] == 1 else 'claim'} "
            f"{_quantity(unpriced['hours'])} hours with no usable Rate, so that labour is unpriced: disclosed here, never "
            "valued at zero, and no rate is borrowed from another person. Any Job Work Pay they record is included."
        )
    else:
        parts.append("Every ticket's labour is priced.")
    parts.extend(_left_out(result))
    return " ".join(parts)


def _flagged_completeness(result: dict[str, Any], status_counts: StatusCounts) -> str:
    if result["availability"]["status"] != "available":
        return result["availability"]["reason"]
    contributing = result["coverage"]["contributing_tickets"]
    parts = [f"{_count(contributing, 'flagged duplicate')} valued."]
    unpriced = _unpriced(result, status_counts)
    if unpriced["tickets"]:
        parts.append(
            f"{_count(unpriced['tickets'], 'of them', 'of them')} {'has' if unpriced['tickets'] == 1 else 'have'} "
            f"{_quantity(unpriced['hours'])} hours with no usable Rate, unpriced and never valued at zero; any Job Work "
            "Pay they record is included."
        )
    elif contributing:
        parts.append("Every one has its labour priced.")
    parts.extend(_left_out(result))
    return " ".join(parts)


def _extra_claim_figure(result: dict[str, Any]) -> dict[str, Any]:
    groups = [
        {**group, "examples": _examples(group["ticket_numbers"])} for group in result.get("possible_duplicates") or []
    ]
    if result["availability"]["status"] != "available":
        completeness = result["availability"]["reason"]
    else:
        parts = [
            f"{_count(len(groups), 'exact repeat')}, not flagged, holding {_count(result['tickets'], 'ticket')} with "
            f"every component priced: {_count(sum(group['extra_claims'] for group in groups), 'extra claim')} in all."
            if groups else "No exact repeat, not flagged, is valued under these filters."
        ]
        for item in result["coverage"]["excluded"]:
            if item["code"] == "member_labour_unpriced":
                parts.append(
                    f"{_count(item['possible_duplicates'], 'exact repeat')} left out because a ticket's labour is "
                    f"unpriced ({_rows(item['excel_rows'])}); not valued at zero."
                )
            else:
                parts.append(f"{_count(item['tickets'], 'ticket')} could not be compared: {item['message']}.")
        parts.append(
            "No such value is given for other possible duplicates: tickets that overlap or partly match need the kept "
            "claim identified by a reviewer first."
        )
        completeness = " ".join(parts)
    return {**_figure(EXTRA_CLAIM, result, completeness), "possible_duplicates": groups}


def _reviewed_alternative(
    known: dict[str, Any], reviewed: dict[str, Any], replaced_rows: list[int], status_counts: StatusCounts,
) -> dict[str, Any]:
    excluded = next(
        (item for item in (reviewed["coverage"] or {"excluded": []})["excluded"] if item["code"] == "replaced_by_review"),
        None,
    )
    in_filter = list(excluded["excel_rows"]) if excluded else []
    left_out = None
    if known["value"] is not None and reviewed["value"] is not None:
        difference = Decimal(str(known["value"])) - Decimal(str(reviewed["value"]))
        left_out = int(difference) if difference == difference.to_integral_value() else float(difference)
    if reviewed["availability"]["status"] != "available":
        completeness = reviewed["availability"]["reason"]
    else:
        parts = [
            f"{_count(len(in_filter), 'replaced ticket')} left out"
            + (f" ({_rows(in_filter)}), worth BBD {_money(left_out)} of known components." if in_filter else ".")
        ]
        outside = len(replaced_rows) - len(in_filter)
        if outside:
            parts.append(f"{_count(outside, 'more replaced ticket')} {'is' if outside == 1 else 'are'} outside these filters.")
        unpriced = _unpriced(reviewed, status_counts)
        if unpriced["tickets"]:
            parts.append(
                f"{_tickets_with_status(unpriced)} still {'claims' if unpriced['tickets'] == 1 else 'claim'} "
                f"{_quantity(unpriced['hours'])} unpriced hours, never valued at zero."
            )
        completeness = " ".join(parts)
    return {
        **_figure(REVIEWED, reviewed, completeness),
        "replaced_tickets": list(replaced_rows),
        "replaced_in_filter": in_filter,
        "left_out_value": left_out,
    }


def _left_out(result: dict[str, Any]) -> list[str]:
    return [
        f"{_count(item['tickets'], 'ticket')} left out because {item['message']} ({_rows(item['excel_rows'])})."
        for item in result["coverage"]["excluded"]
    ]


def _examples(ticket_numbers: list[str | None]) -> list[str]:
    """The evidence report's example letters naming any of these tickets, for reading the group aloud."""
    return sorted({ANNOTATIONS.tickets[number]["example"] for number in ticket_numbers if number in ANNOTATIONS.tickets})


def _tickets_with_status(unpriced: dict[str, Any]) -> str:
    """'122 Pending tickets', or '3 tickets (2 Pending, 1 Approved)' when the statuses are mixed."""
    statuses = unpriced["statuses"]
    if len(statuses) == 1 and statuses[0]["status"]:
        return _count(unpriced["tickets"], f"{statuses[0]['status']} ticket")
    detail = ", ".join(f"{item['tickets']} {item['status'] or 'unreadable status'}" for item in statuses)
    return f"{_count(unpriced['tickets'], 'ticket')} ({detail})"


def _count(count: int, one: str, many: str | None = None) -> str:
    return f"{count:,} {one if count == 1 else (many or one + 's')}"


def _quantity(value: Any) -> str:
    return f"{value:,}" if isinstance(value, int) else f"{value:,.2f}".rstrip("0").rstrip(".")


def _money(value: Any) -> str:
    return f"{value:,.2f}" if value is not None else "unknown"


def _rows(rows: list[int], limit: int = 10) -> str:
    """'Excel row 855', or 'Excel rows 7, 8', naming at most `limit` rows."""
    shown = ", ".join(str(row) for row in rows[:limit])
    listed = shown if len(rows) <= limit else f"{shown} and {len(rows) - limit} more"
    return f"Excel row{'s' if len(rows) != 1 else ''} {listed}"
