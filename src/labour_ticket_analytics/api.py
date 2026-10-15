"""The local HTTP JSON API and the built frontend, served from one port."""

from __future__ import annotations

import datetime as dt
import threading
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from labour_ticket_analytics import __version__
from labour_ticket_analytics import flagged, processing_queue
from labour_ticket_analytics.annotations import ANNOTATIONS
from labour_ticket_analytics.filters import DEFAULT_DATE_BASIS, FilterError, Filters
from labour_ticket_analytics.metrics import METRICS, Metric, MetricError, registry_payload
from labour_ticket_analytics.normalized import normalize_label
from labour_ticket_analytics.review import (
    ALIAS_DECISION_VALUES, ReviewError, ReviewStore, outcome_label, pair_key, proposing_rows,
)
from labour_ticket_analytics.rules import RULES, TIERS, Aliases, alias_key
from labour_ticket_analytics.store import SnapshotStore
from labour_ticket_analytics.timeparse import PARSER_VERSION, TimeParse, compare
from labour_ticket_analytics.versions import versions
from labour_ticket_analytics.workbook import WorkbookError, fingerprint_workbook, import_workbook

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
DEFAULT_AS_OF = dt.date(2026, 10, 8)
AS_OF_NOTE = (
    "Analytical as-of date. The export carries no timestamp, so this is an assumption "
    "based on the latest Created date; it is never today's date."
)
AS_OF_CHANGED_NOTE = (
    "Analytical as-of date set by the analyst in place of the default assumption of {default} "
    "(the latest Created date). Ages are measured to it; it is never today's date."
)

# The header tiles, in display order. Each is a registry metric, never a constant.
TILES = (
    "ticket_count", "flagged_duplicate_count", "unflagged_exact_repeat_count", "pending_count", "approved_not_keyed_count",
)
TILES_OVERLAP_NOTE = (
    "These tiles overlap conceptually and do not sum to the Tickets in the Snapshot: they count Tickets, "
    "or possible duplicates with their Tickets shown, from the same population, and one Ticket can fall "
    "under more than one tile."
)

ALIASES_NOTE = (
    "Proposed by the Name-space variant: the same claim under two names that are equal once spaces and case are "
    "ignored. A confirmed Alias lets the Work-period conflict rule compare both labels' tickets as one employee; "
    "it never merges the labels, and the employee-label count still counts both. A shared email is never a reason."
)

REVIEW_PRIORITIES_NOTE = (
    "Ordered by review priority, not by any probability of wrongdoing; employees and supervisors are never ranked. "
    "A filter selects a possible duplicate when any of its tickets matches, and every ticket stays listed."
)

MISSING_FRONTEND_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Labour Ticket Analytics</title></head>
<body style="font-family: system-ui, sans-serif; max-width: 40rem; margin: 3rem auto; line-height: 1.5">
<h1>Labour Ticket Analytics</h1>
<p>The service is running and the JSON API is available at <code>/api/snapshot</code>,
but the frontend has not been built yet.</p>
<p>Build it once, then relaunch:</p>
<pre>npm --prefix frontend ci
npm --prefix frontend run build</pre>
</body></html>
"""


@dataclass
class AppState:
    store: SnapshotStore
    active_fingerprint: str
    as_of: dt.date
    workbook_path: Path
    review: ReviewStore
    frontend_dist: Path = FRONTEND_DIST
    import_lock: threading.Lock = field(default_factory=threading.Lock)
    # Held while an Alias decision is saved and the rules run again, so the stored Candidates always
    # reflect the latest decisions.
    rules_lock: threading.Lock = field(default_factory=threading.Lock)

    def aliases(self, fingerprint: str) -> Aliases:
        """The Snapshot's confirmed Aliases, as the rules read them."""
        return Aliases(self.review.confirmed_aliases(fingerprint))

    def reimport(self) -> bool:
        """Read the workbook at the launch path again and make it the active Snapshot.

        Identical content (the same fingerprint) is a no-op and is not parsed
        again. Different content becomes a new Snapshot beside the old one,
        never extra Tickets in it. A workbook that cannot be imported raises
        WorkbookError and leaves the active Snapshot as it was. Returns
        whether a new Snapshot was added.
        """
        with self.import_lock:
            if not self.workbook_path.is_file():
                raise WorkbookError(f"workbook not found: {self.workbook_path}")
            fingerprint = fingerprint_workbook(self.workbook_path)
            added = False
            if not self.store.has_snapshot(fingerprint):
                snapshot = import_workbook(self.workbook_path)
                added = self.store.add_snapshot(snapshot, self.aliases(snapshot.fingerprint))
                fingerprint = snapshot.fingerprint
            self.active_fingerprint = fingerprint
            return added


class AsOfChange(BaseModel):
    date: dt.date


class OutcomeChange(BaseModel):
    """A Review Outcome saved on a Ticket pair, with who saved it and why."""

    outcome: str
    note: str = ""
    reference: str = ""
    reviewer: str
    rationale: str = ""


class AliasChange(BaseModel):
    """A reviewer's decision on a proposed Alias: the two employee labels, confirmed or rejected, and why."""

    labels: list[str]
    decision: str
    reviewer: str
    rationale: str = ""


class LinkChange(BaseModel):
    """Who makes or removes a kept/replaced link, and why."""

    reviewer: str
    rationale: str = ""


def filter_query(
    date_basis: str = DEFAULT_DATE_BASIS,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    job: list[int] = Query(default=[]),
    status: list[str] = Query(default=[]),
) -> dict:
    """The global filter bar as query parameters; validated against the Snapshot by Filters.build."""
    return {"date_basis": date_basis, "date_from": date_from, "date_to": date_to, "jobs": job, "statuses": status}


def require_same_origin(request: Request) -> None:
    """Refuse a state-changing request that a browser sent on behalf of another site.

    Browsers attach Origin to cross-site POSTs; a request without one comes
    from a local tool such as curl and is allowed.
    """
    origin = request.headers.get("origin")
    if origin is None:
        return
    expected = f"{request.url.scheme}://{request.headers.get('host', '')}"
    if origin != expected:
        raise HTTPException(status_code=403, detail="cross-site requests may not change the application state")


def create_app(state: AppState) -> FastAPI:
    app = FastAPI(title="Labour Ticket Analytics", version=__version__, docs_url=None, redoc_url=None)

    def as_of_payload() -> dict:
        is_default = state.as_of == DEFAULT_AS_OF
        return {
            "date": state.as_of.isoformat(),
            "is_assumption": True,
            "is_default": is_default,
            "default": DEFAULT_AS_OF.isoformat(),
            "note": AS_OF_NOTE if is_default else AS_OF_CHANGED_NOTE.format(default=DEFAULT_AS_OF.isoformat()),
        }

    def context(fingerprint: str) -> dict:
        """What every response carrying numbers also carries: the Snapshot, as-of date and versions in effect."""
        return {"snapshot_fingerprint": fingerprint, "as_of": as_of_payload(), "versions": versions()}

    def header_payload() -> dict:
        fingerprint = state.active_fingerprint
        snapshot = state.store.snapshot_header(fingerprint)
        if snapshot is None:
            raise HTTPException(status_code=503, detail="no active Snapshot")
        return {"snapshot": snapshot, **context(fingerprint)}

    def active_filters(fingerprint: str, query: dict) -> Filters:
        try:
            return Filters.build(fields=state.store.fields(fingerprint), **query)
        except FilterError as error:
            raise HTTPException(status_code=422, detail=error.payload()) from error

    def registry_metric(metric_id: str) -> Metric:
        metric = METRICS.get(metric_id)
        if metric is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "unknown_metric", "field": "metric_id", "message": f"no metric {metric_id!r} in the registry"},
            )
        return metric

    def evaluate(fingerprint: str, metric_id: str, filters: Filters, **options) -> dict:
        metric = registry_metric(metric_id)
        try:
            return state.store.evaluate_metric(fingerprint, metric, filters, state.as_of, **options)
        except MetricError as error:
            raise metric_failure(error) from error

    def metric_failure(error: MetricError) -> HTTPException:
        return HTTPException(status_code=error.status, detail=error.payload())

    def saved_outcome(saved: dict, excel_rows: list[int]) -> dict:
        """A pair's saved Review Outcome label, Not reviewed when none was saved."""
        record = saved.get(pair_key(*excel_rows))
        return record["outcome"] if record else outcome_label("not_reviewed")

    def with_outcomes(fingerprint: str, item: dict, saved: dict | None = None) -> dict:
        """A possible duplicate whose Candidates each carry their pair's Review Outcome, Not reviewed by default.

        Display only here: the tier reads settled pairs separately (rules.settled_rows), never this label.
        """
        saved = state.review.outcomes(fingerprint) if saved is None else saved
        candidates = [
            {**candidate, "outcome": saved_outcome(saved, candidate["excel_rows"])} for candidate in item["candidates"]
        ]
        return {**item, "candidates": candidates}

    def with_review(fingerprint: str, payload: dict) -> dict:
        """The evidence with its review block: an outcome per Candidate pair, the links and history of its members."""
        numbers = {member["excel_row"]: member["ticket_number"] for member in payload["members"]}
        pairs: dict[tuple[int, int], set[str]] = {}
        for candidate in payload["candidates"]:
            pairs.setdefault(pair_key(*candidate["excel_rows"]), set()).add(candidate["rule_id"])
        # The Aliases about two of the members' labels: proposed here, or widening a rule here once confirmed.
        labels = {member["employee_label"] for member in payload["members"]}
        proposals = [
            proposal for proposal in state.store.alias_proposals(fingerprint).values()
            if set(proposal["labels"]) <= labels
        ]
        review = state.review.for_possible_duplicate(
            fingerprint,
            [
                {"excel_rows": list(pair), "ticket_numbers": [numbers[pair[0]], numbers[pair[1]]], "rule_ids": sorted(rule_ids)}
                for pair, rule_ids in sorted(pairs.items())
            ],
            list(numbers),
            proposals,
        )
        return {**with_outcomes(fingerprint, payload), "review": review}

    @app.get("/api/snapshot")
    def snapshot_header() -> dict:
        return header_payload()

    @app.post("/api/snapshot/reimport")
    def reimport(request: Request) -> dict:
        require_same_origin(request)
        try:
            imported = state.reimport()
        except WorkbookError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {"imported": imported, **header_payload()}

    @app.get("/api/snapshots")
    def snapshots() -> dict:
        fingerprint = state.active_fingerprint
        return {
            "snapshots": [
                {**snapshot, "active": snapshot["fingerprint"] == fingerprint}
                for snapshot in state.store.snapshots()
            ],
            **context(fingerprint),
        }

    @app.get("/api/as-of")
    def as_of() -> dict:
        return context(state.active_fingerprint)

    @app.put("/api/as-of")
    def change_as_of(change: AsOfChange, request: Request) -> dict:
        require_same_origin(request)
        state.as_of = change.date
        return context(state.active_fingerprint)

    @app.get("/api/metrics")
    def metric_registry() -> dict:
        fingerprint = state.active_fingerprint
        return {
            "registry_version": versions()["registry"],
            "metrics": registry_payload(state.store.fields(fingerprint)),
            **context(fingerprint),
        }

    @app.get("/api/metrics/{metric_id}")
    def metric_value(
        metric_id: str, query: dict = Depends(filter_query), group_by: str | None = None, rows: bool = False
    ) -> dict:
        fingerprint = state.active_fingerprint
        filters = active_filters(fingerprint, query)
        return {**evaluate(fingerprint, metric_id, filters, group_by=group_by, include_rows=rows), **context(fingerprint)}

    @app.get("/api/metrics/{metric_id}/buckets/{bucket_id}")
    def metric_bucket(metric_id: str, bucket_id: str, query: dict = Depends(filter_query)) -> dict:
        """The Tickets one bucket of a metric counts, under the same filters and as-of date as its chart."""
        fingerprint = state.active_fingerprint
        metric = registry_metric(metric_id)
        filters = active_filters(fingerprint, query)
        try:
            listed = state.store.metric_bucket_rows(fingerprint, metric, filters, state.as_of, bucket_id)
        except MetricError as error:
            raise metric_failure(error) from error
        return {**listed, **context(fingerprint)}

    @app.get("/api/overview/processing-queue")
    def processing_queue_view(query: dict = Depends(filter_query)) -> dict:
        """The two age-since-submission charts, each a registry metric counted by its buckets."""
        fingerprint = state.active_fingerprint
        filters = active_filters(fingerprint, query)
        return {
            "charts": [
                processing_queue.chart(queue, METRICS[queue.metric_id], evaluate(fingerprint, queue.metric_id, filters))
                for queue in processing_queue.QUEUES
            ],
            "caption": processing_queue.CAPTION,
            "note": processing_queue.NOTE,
            "grain": "Ticket",
            "filters": filters.payload(),
            **context(fingerprint),
        }

    @app.get("/api/review-priorities")
    def review_priorities(query: dict = Depends(filter_query)) -> dict:
        fingerprint = state.active_fingerprint
        filters = active_filters(fingerprint, query)
        saved = state.review.outcomes(fingerprint)
        settled = state.review.settled_pairs(fingerprint)
        return {
            "possible_duplicates": [
                with_outcomes(fingerprint, item, saved)
                for item in state.store.possible_duplicates(fingerprint, filters, settled)
            ],
            "tiers": [tier.payload() for tier in TIERS],
            "rules": [rule.payload() for rule in RULES.values()],
            "note": REVIEW_PRIORITIES_NOTE,
            "filters": filters.payload(),
            **context(fingerprint),
        }

    @app.get("/api/flagged-duplicates")
    def flagged_duplicates(query: dict = Depends(filter_query)) -> dict:
        """Every flagged duplicate the tile counts, with counterpart found or unresolved, shown apart from the tile."""
        fingerprint = state.active_fingerprint
        filters = active_filters(fingerprint, query)
        saved = state.review.outcomes(fingerprint)
        entries = state.store.flagged_duplicates(fingerprint, filters, state.review.settled_pairs(fingerprint))
        for entry in entries:
            for counterpart in entry["counterparts"]:
                counterpart["outcome"] = saved_outcome(saved, counterpart["excel_rows"])
        return {
            "flagged_duplicates": entries,
            "counts": flagged.counts(entries),
            "counterpart_statuses": [status.payload() for status in flagged.COUNTERPART_STATUSES],
            "metric_id": "flagged_duplicate_count",
            "note": flagged.NOTE,
            "filters": filters.payload(),
            **context(fingerprint),
        }

    @app.get("/api/annotations")
    def annotations() -> dict:
        fingerprint = state.active_fingerprint
        excel_rows = state.store.excel_rows_by_ticket_number(fingerprint, ANNOTATIONS.tickets)
        return {**ANNOTATIONS.payload(excel_rows), **context(fingerprint)}

    @app.get("/api/filters")
    def filter_options() -> dict:
        fingerprint = state.active_fingerprint
        return {**state.store.filter_options(fingerprint), **context(fingerprint)}

    @app.get("/api/overview/tiles")
    def tiles(query: dict = Depends(filter_query)) -> dict:
        fingerprint = state.active_fingerprint
        filters = active_filters(fingerprint, query)
        results = [evaluate(fingerprint, metric_id, filters) for metric_id in TILES]
        return {
            "tiles": [
                {
                    "metric_id": result["metric"]["id"],
                    "label": result["metric"]["label"],
                    "value": result["value"],
                    "tickets": result.get("tickets"),
                    "unit": result["metric"]["unit"],
                    "definition": result["metric"]["definition"],
                    "percentage": result["percentage"],
                    "warnings": result["warnings"],
                }
                for result in results
            ],
            "note": TILES_OVERLAP_NOTE,
            "grain": "Ticket",
            "filters": filters.payload(),
            **context(fingerprint),
        }

    def no_ticket(fingerprint: str, excel_row: int) -> HTTPException:
        return HTTPException(status_code=404, detail=f"no Ticket at Excel row {excel_row} in Snapshot {fingerprint[:12]}")

    @app.get("/api/snapshots/{fingerprint}/tickets/{excel_row}")
    def ticket(fingerprint: str, excel_row: int) -> dict:
        payload = state.store.ticket(fingerprint, excel_row)
        if payload is None:
            raise no_ticket(fingerprint, excel_row)
        return {**payload, **context(fingerprint)}

    def time_parse(fingerprint: str, excel_row: int) -> TimeParse:
        parse = state.store.time_parse(fingerprint, excel_row)
        if parse is None:
            raise no_ticket(fingerprint, excel_row)
        return parse

    @app.get("/api/snapshots/{fingerprint}/tickets/{excel_row}/possible-duplicate")
    def possible_duplicate(fingerprint: str, excel_row: int, query: dict = Depends(filter_query)) -> dict:
        if state.store.ticket(fingerprint, excel_row) is None:
            raise no_ticket(fingerprint, excel_row)
        payload = state.store.possible_duplicate_evidence(
            fingerprint, excel_row, active_filters(fingerprint, query), state.review.settled_pairs(fingerprint),
        )
        if payload is None:
            raise HTTPException(
                status_code=404, detail=f"the Ticket at Excel row {excel_row} is in no possible duplicate"
            )
        return {**with_review(fingerprint, payload), **context(fingerprint)}

    @app.get("/api/snapshots/{fingerprint}/tickets/{excel_row}/evidence")
    def ticket_evidence(fingerprint: str, excel_row: int, query: dict = Depends(filter_query)) -> dict:
        """One Ticket's evidence on its own, such as a flagged duplicate no rule links."""
        payload = state.store.ticket_evidence(fingerprint, excel_row, active_filters(fingerprint, query))
        if payload is None:
            raise no_ticket(fingerprint, excel_row)
        return {**payload, **context(fingerprint)}

    def require_snapshot(fingerprint: str) -> None:
        if not state.store.has_snapshot(fingerprint):
            raise HTTPException(status_code=404, detail=f"no Snapshot {fingerprint[:12]}")

    def review_failure(error: ReviewError) -> HTTPException:
        return HTTPException(status_code=error.status, detail=error.payload())

    def candidate_pair(fingerprint: str, first_row: int, second_row: int) -> tuple[int, int]:
        """The pair key, or 404 unless a Candidate links the two Tickets: outcomes attach to Candidate pairs only."""
        require_snapshot(fingerprint)
        if first_row == second_row or not state.store.candidate_rule_ids(fingerprint, first_row, second_row):
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "no_candidate",
                    "field": "excel_rows",
                    "message": f"no Candidate links rows {first_row} and {second_row} in Snapshot {fingerprint[:12]}",
                },
            )
        return pair_key(first_row, second_row)

    @app.get("/api/snapshots/{fingerprint}/review")
    def review_summary(fingerprint: str) -> dict:
        require_snapshot(fingerprint)
        return {**state.review.summary(fingerprint), **context(fingerprint)}

    def alias_proposal(fingerprint: str, labels: list[str]) -> dict:
        """The proposal for two employee labels, as written or normalized; 404 unless a Name-space variant made one."""
        normalized = [normalize_label(label) for label in labels]
        if len(normalized) != 2 or None in normalized or normalized[0] == normalized[1]:
            raise HTTPException(
                status_code=422,
                detail={"code": "two_labels_required", "field": "labels", "message": "give two different employee labels"},
            )
        key = alias_key(*normalized)
        proposal = state.store.alias_proposals(fingerprint).get(key)
        if proposal is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "no_alias_proposal",
                    "field": "labels",
                    "message": f"no Name-space variant proposes an Alias for {key[0]!r} and {key[1]!r} in Snapshot "
                    f"{fingerprint[:12]}",
                },
            )
        return proposal

    @app.get("/api/snapshots/{fingerprint}/aliases")
    def alias_list(fingerprint: str) -> dict:
        require_snapshot(fingerprint)
        return {
            "aliases": state.review.aliases(fingerprint, state.store.alias_proposals(fingerprint).values()),
            "decision_values": [value.payload() for value in ALIAS_DECISION_VALUES],
            "note": ALIASES_NOTE,
            **context(fingerprint),
        }

    @app.put("/api/snapshots/{fingerprint}/aliases")
    def decide_alias(fingerprint: str, change: AliasChange, request: Request) -> dict:
        """Confirm or reject a proposed Alias; a change runs every rule again over the Snapshot."""
        require_same_origin(request)
        require_snapshot(fingerprint)
        proposal = alias_proposal(fingerprint, change.labels)
        with state.rules_lock:
            try:
                saved = state.review.save_alias(
                    fingerprint, proposal, state.store.ticket_numbers(fingerprint, proposing_rows(proposal)),
                    decision=change.decision, reviewer=change.reviewer, rationale=change.rationale,
                )
            except ReviewError as error:
                raise review_failure(error) from error
            rerun = state.store.rerun_rules(fingerprint, state.aliases(fingerprint)) if saved["changed"] else None
        return {**saved, "rerun": rerun or {"added": [], "removed": []}, "rules_ran": rerun is not None, **context(fingerprint)}

    @app.get("/api/snapshots/{fingerprint}/pairs/{first_row}/{second_row}")
    def pair_explanation(fingerprint: str, first_row: int, second_row: int, query: dict = Depends(filter_query)) -> dict:
        """Why two Tickets are or are not linked: any two Tickets, with or without a Candidate."""
        require_snapshot(fingerprint)
        if first_row == second_row:
            raise HTTPException(
                status_code=422,
                detail={"code": "two_tickets_required", "field": "excel_rows", "message": "give two different Excel rows"},
            )
        payload = state.store.pair_explanation(fingerprint, first_row, second_row, active_filters(fingerprint, query))
        if payload is None:
            missing = first_row if state.store.ticket(fingerprint, first_row) is None else second_row
            raise no_ticket(fingerprint, missing)
        return {**payload, **context(fingerprint)}

    @app.get("/api/snapshots/{fingerprint}/pairs/{first_row}/{second_row}/outcome")
    def pair_outcome(fingerprint: str, first_row: int, second_row: int) -> dict:
        pair = candidate_pair(fingerprint, first_row, second_row)
        numbers = state.store.ticket_numbers(fingerprint, pair)
        return {**state.review.outcome(fingerprint, *pair, numbers), **context(fingerprint)}

    @app.put("/api/snapshots/{fingerprint}/pairs/{first_row}/{second_row}/outcome")
    def save_pair_outcome(fingerprint: str, first_row: int, second_row: int, change: OutcomeChange, request: Request) -> dict:
        require_same_origin(request)
        pair = candidate_pair(fingerprint, first_row, second_row)
        numbers = state.store.ticket_numbers(fingerprint, pair)
        try:
            saved = state.review.save_outcome(fingerprint, *pair, numbers, **change.model_dump())
        except ReviewError as error:
            raise review_failure(error) from error
        return {**saved, **context(fingerprint)}

    def linkable(fingerprint: str, replaced_row: int, retained_row: int) -> None:
        """Both Tickets must sit in one possible duplicate, so every link is made from the evidence."""
        for row in (replaced_row, retained_row):
            if state.store.ticket(fingerprint, row) is None:
                raise no_ticket(fingerprint, row)
        if retained_row not in state.store.possible_duplicate_rows(fingerprint, replaced_row):
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "not_in_one_possible_duplicate",
                    "field": "retained_row",
                    "message": f"rows {replaced_row} and {retained_row} are not in the same possible duplicate",
                },
            )

    @app.put("/api/snapshots/{fingerprint}/replacement-links/{replaced_row}/{retained_row}")
    def make_link(fingerprint: str, replaced_row: int, retained_row: int, change: LinkChange, request: Request) -> dict:
        require_same_origin(request)
        require_snapshot(fingerprint)
        if replaced_row != retained_row:
            linkable(fingerprint, replaced_row, retained_row)
        numbers = state.store.ticket_numbers(fingerprint, (replaced_row, retained_row))
        try:
            link = state.review.link(fingerprint, replaced_row, retained_row, numbers, **change.model_dump())
        except ReviewError as error:
            raise review_failure(error) from error
        return {**link, **context(fingerprint)}

    @app.delete("/api/snapshots/{fingerprint}/replacement-links/{replaced_row}/{retained_row}")
    def remove_link(fingerprint: str, replaced_row: int, retained_row: int, change: LinkChange, request: Request) -> dict:
        require_same_origin(request)
        require_snapshot(fingerprint)
        try:
            link = state.review.unlink(fingerprint, replaced_row, retained_row, **change.model_dump())
        except ReviewError as error:
            raise review_failure(error) from error
        return {**link, **context(fingerprint)}

    @app.get("/api/snapshots/{fingerprint}/time-parses")
    def time_parse_summary(fingerprint: str) -> dict:
        summary = state.store.time_parse_summary(fingerprint)
        if summary is None:
            raise HTTPException(status_code=404, detail=f"no Snapshot {fingerprint[:12]}")
        return {"parser_version": PARSER_VERSION, "by_status": summary, **context(fingerprint)}

    @app.get("/api/snapshots/{fingerprint}/tickets/{excel_row}/time")
    def ticket_time(fingerprint: str, excel_row: int) -> dict:
        return {"excel_row": excel_row, **time_parse(fingerprint, excel_row).payload(), **context(fingerprint)}

    @app.get("/api/snapshots/{fingerprint}/time-comparison")
    def time_comparison(fingerprint: str, excel_row: list[int] = Query(default=[])) -> dict:
        if len(excel_row) != 2:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "two_tickets_required",
                    "field": "excel_row",
                    "message": "give exactly two Excel rows to compare",
                },
            )
        parses = [time_parse(fingerprint, row) for row in excel_row]
        return {
            **compare(*parses),
            "tickets": [{"excel_row": row, **parse.payload()} for row, parse in zip(excel_row, parses)],
            **context(fingerprint),
        }

    index_html = state.frontend_dist / "index.html"
    if index_html.is_file():
        app.mount("/assets", StaticFiles(directory=state.frontend_dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def frontend(path: str) -> FileResponse:
            if path == "api" or path.startswith("api/"):
                raise HTTPException(status_code=404, detail=f"no such API path: /{path}")
            candidate = (state.frontend_dist / path).resolve()
            if path and candidate.is_file() and state.frontend_dist.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(index_html)

    else:

        @app.get("/", include_in_schema=False)
        def missing_frontend() -> HTMLResponse:
            return HTMLResponse(MISSING_FRONTEND_HTML)

    return app
