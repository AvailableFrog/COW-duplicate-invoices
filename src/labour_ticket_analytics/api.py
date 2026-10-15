"""The local HTTP JSON API and the built frontend, served from one port."""

from __future__ import annotations

import datetime as dt
import threading
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from labour_ticket_analytics import __version__
from labour_ticket_analytics import (
    claimed_hours, data_readiness, exports, flagged, pattern_matrix, plans, processing_queue, timing,
    value_context,
)
from labour_ticket_analytics.annotations import ANNOTATIONS
from labour_ticket_analytics.filters import DEFAULT_DATE_BASIS, FilterError, Filters
from labour_ticket_analytics.metrics import METRICS, Metric, MetricError, registry_payload
from labour_ticket_analytics.normalized import normalize_label
from labour_ticket_analytics.providers import NullProvider, PlanProvider
from labour_ticket_analytics.result_cache import ResultCache
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
    # What turns a question into a plan; release one has no model (ADR 0001).
    provider: PlanProvider = field(default_factory=NullProvider)
    # Executed Explore plans, reused for identical requests within one Snapshot, as-of date, set of versions
    # and review revision, and discarded when any of them changes.
    results: ResultCache = field(default_factory=ResultCache)
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
        if metric.reads_review_links:
            # Only explicit kept/replaced links reach a figure; outcomes and notes never do.
            options = {**options, "replaced_rows": state.review.replaced_rows(fingerprint)}
        try:
            return state.store.evaluate_metric(fingerprint, metric, filters, state.as_of, **options)
        except MetricError as error:
            raise metric_failure(error) from error

    def reporting_window(
        fingerprint: str, window_from: dt.date | None, window_to: dt.date | None,
    ) -> data_readiness.ReportingWindow | None:
        """The reporting window asked for, each end defaulting to the years Created covers; 422 when reversed."""
        try:
            return data_readiness.ReportingWindow.build(
                state.store.default_reporting_window(fingerprint), window_from, window_to,
            )
        except FilterError as error:
            raise HTTPException(status_code=422, detail=error.payload()) from error

    def window_bounds(window: data_readiness.ReportingWindow | None) -> tuple[dt.date, dt.date] | None:
        return window.bounds if window is not None else None

    def unresolved_aliases(fingerprint: str, filters: Filters) -> list[dict]:
        """Proposed Aliases nobody has confirmed or rejected, any of whose proposing Tickets is inside the filters."""
        aliases = state.review.aliases(fingerprint, state.store.alias_proposals(fingerprint).values())
        rows = {row for alias in aliases for pair in alias["proposed_by"] for row in pair}
        return data_readiness.unresolved_aliases(aliases, state.store.members_inside(fingerprint, filters, rows))

    def readiness_rows(
        fingerprint: str,
        filters: Filters,
        check: data_readiness.Check,
        window: data_readiness.ReportingWindow | None,
    ) -> tuple[dict | None, list[dict]]:
        """A readiness check's metric result (None for the Alias proposals) and exactly the rows it counts."""
        if check.metric_id is None:
            aliases = unresolved_aliases(fingerprint, filters)
            numbers = state.store.ticket_numbers(
                fingerprint, {row for alias in aliases for pair in alias["proposed_by"] for row in pair},
            )
            return None, [
                data_readiness.alias_row(
                    alias, numbers, lambda row: state.store.possible_duplicate_name(fingerprint, row, filters),
                )
                for alias in aliases
            ]
        result = evaluate(fingerprint, check.metric_id, filters, include_rows=True, window=window_bounds(window))
        tickets = state.store.readiness_tickets(fingerprint, filters, result.get("contributing_rows", []))
        return result, [data_readiness.ticket_row(check, ticket, window) for ticket in tickets]

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
        metric_id: str,
        query: dict = Depends(filter_query),
        group_by: str | None = None,
        rows: bool = False,
        window_from: dt.date | None = None,
        window_to: dt.date | None = None,
    ) -> dict:
        fingerprint = state.active_fingerprint
        filters = active_filters(fingerprint, query)
        options: dict = {"group_by": group_by, "include_rows": rows}
        if registry_metric(metric_id).reads_reporting_window:
            window = reporting_window(fingerprint, window_from, window_to)
            options["window"] = window_bounds(window)
            extra = {"reporting_window": window.payload() if window else None}
        else:
            extra = {}
        return {**evaluate(fingerprint, metric_id, filters, **options), **extra, **context(fingerprint)}

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

    def compiled_plan(fingerprint: str, body: dict) -> tuple[plans.Plan, plans.Inherited, Filters]:
        """The request's plan and inherited Overview filters, validated and compiled; raises PlanError."""
        fields = state.store.fields(fingerprint)
        issues: list[plans.PlanIssue] = []
        plan = inheritance = None
        try:
            plan = plans.validate(body.get("plan"), fields)
        except plans.PlanError as error:
            issues.extend(error.issues)
        try:
            inheritance = plans.inherited(body.get("inherited"), fields)
        except plans.PlanError as error:
            issues.extend(error.issues)
        if issues:
            raise plans.PlanError(issues)
        return plan, inheritance, plans.compile_filters(plan, inheritance, fields, state.as_of)

    @app.get("/api/explore")
    def explore_catalogue() -> dict:
        """What the Explore chips may hold: the allowlists, the Snapshot's field values and the six starter plans."""
        fingerprint = state.active_fingerprint
        return {
            **plans.catalogue(state.store.fields(fingerprint), state.store.field_values(fingerprint)),
            "provider": state.provider.payload(),
            **context(fingerprint),
        }

    @app.post("/api/plans/validate")
    def validate_plan(body: dict = Body(...)) -> dict:
        """Whether a plan is inside the allowlists; every problem is listed with the field at fault."""
        fingerprint = state.active_fingerprint
        try:
            plan, inheritance, filters = compiled_plan(fingerprint, body)
        except plans.PlanError as error:
            return {"valid": False, "plan": None, "errors": [issue.payload() for issue in error.issues], **context(fingerprint)}
        return {
            "valid": True,
            "plan": plan.payload(),
            "errors": [],
            "inherited_filters": inheritance.payload(),
            "filters": filters.payload(),
            "date_range": plans.date_range_payload(plan, filters, state.as_of),
            **context(fingerprint),
        }

    def require_shown_snapshot(body: dict, fingerprint: str) -> None:
        """Refuse (409) a request naming the Snapshot its result is shown for once another Snapshot is active."""
        shown_for = body.get("snapshot_fingerprint")
        if shown_for is not None and shown_for != fingerprint:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "stale_snapshot",
                    "field": "snapshot_fingerprint",
                    "message": f"The Snapshot changed from {str(shown_for)[:12]} to {fingerprint[:12]}; "
                    "run the plan again to see it against the active Snapshot.",
                    "active_snapshot_fingerprint": fingerprint,
                },
            )

    def run_plan(fingerprint: str, plan: plans.Plan, inheritance: plans.Inherited, filters: Filters) -> plans.Executed:
        metric = plan.metric
        replaced_rows = state.review.replaced_rows(fingerprint) if metric.reads_review_links else ()
        # The default reporting window: read by window metrics, and where a weekly or monthly series ends.
        window = window_bounds(reporting_window(fingerprint, None, None))
        try:
            evaluated, paired = state.store.evaluate_plan(
                fingerprint, metric, filters, state.as_of, plan.dimension, replaced_rows=replaced_rows, window=window,
                time_basis=plan.date_basis if plan.time_grouping else None, paired_metric=plan.paired_metric,
            )
        except MetricError as error:
            raise metric_failure(error) from error
        job_names = state.store.job_names(fingerprint) if plan.dimension == "Job Number" else {}
        return plans.result(plan, inheritance, filters, evaluated, job_names, state.as_of, window, paired)

    def executed_plan(body: dict) -> tuple[str, plans.Executed, dict]:
        """The request's plan run (or reused from the cache) against the active Snapshot, with the cache's answer.

        The cache key is the validated plan with its inherited and compiled
        filters; its scope is the Snapshot, as-of date, versions and review
        revision, so a change to any of them discards every cached result.
        """
        fingerprint = state.active_fingerprint
        require_shown_snapshot(body, fingerprint)
        try:
            plan, inheritance, filters = compiled_plan(fingerprint, body)
        except plans.PlanError as error:
            raise HTTPException(status_code=422, detail=error.payload()) from error
        revision = state.review.revision
        current = versions()
        scope = (fingerprint, state.as_of.isoformat(), tuple(sorted(current.items())), revision)
        key = state.results.key(
            {"plan": plan.payload(), "inherited": inheritance.payload(), "filters": filters.payload()},
        )
        executed, hit = state.results.get_or_compute(
            scope, key, lambda: run_plan(fingerprint, plan, inheritance, filters),
        )
        cache = {
            "status": "hit" if hit else "miss",
            "key": key[:16],
            "snapshot_fingerprint": fingerprint,
            "as_of": state.as_of.isoformat(),
            "registry_version": current["registry"],
            "review_revision": revision,
        }
        return fingerprint, executed, cache

    @app.post("/api/plans/execute")
    def execute_plan(body: dict = Body(...)) -> dict:
        """A valid plan's values, marks, table, lineage, How calculated and chart, with the Snapshot, as-of date and
        versions beside it, and whether the result came from the cache.

        A request naming the Snapshot its result is shown for is refused (409)
        once another Snapshot is active, so a displayed result is invalidated
        until it is run again.
        """
        fingerprint, executed, cache = executed_plan(body)
        return {**executed.payload, "cache": cache, **context(fingerprint)}

    def overview_plan(plan: dict, inheritance: dict) -> dict:
        """Run an Overview panel's fixed plan under the Overview filters: its request, for drilldowns and
        exports, and its result exactly as /api/plans/execute returns it."""
        request = {"plan": plan, "inherited": inheritance}
        fingerprint, executed, cache = executed_plan(request)
        return {"request": request, "result": {**executed.payload, "cache": cache, **context(fingerprint)}}

    def listing(body: dict) -> tuple[str, plans.Executed, dict, dict]:
        """The drilldown the request asks for: the whole chart (`group` null) or one of its marks by id."""
        fingerprint, executed, cache = executed_plan(body)
        group_id = body.get("group")
        if group_id is not None and not isinstance(group_id, str):
            raise HTTPException(
                status_code=422,
                detail={"code": "invalid_group", "field": "group", "message": "group must be a group id or null"},
            )
        try:
            _, rows, _ = plans.drilldown_selection(executed, group_id)
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "unknown_group",
                    "field": "group",
                    "message": f"the result has no group {group_id!r}; use a group id from its table, or null for "
                    "every ticket in the chart",
                },
            ) from error
        details = state.store.ticket_details(fingerprint, rows)
        return fingerprint, executed, cache, plans.drilldown(executed, group_id, details)

    @app.post("/api/plans/drilldown")
    def drilldown_plan(body: dict = Body(...)) -> dict:
        """Exactly the Tickets behind a chart or one of its marks, from the same evaluation, under the same Snapshot,
        filters, as-of date and versions; `reproduces` says the listing gives back the chart's figure."""
        fingerprint, _, cache, listed = listing(body)
        return {**listed, "cache": cache, **context(fingerprint)}

    def csv_response(fingerprint: str, name: str, header: list[str], rows: list[list]) -> Response:
        provenance = (fingerprint, state.as_of.isoformat(), versions()["registry"])
        filename = f"explore-{name}-{fingerprint[:12]}-as-of-{state.as_of.isoformat()}.csv"
        return Response(
            content=exports.csv_text(header, rows, provenance),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.post("/api/plans/table.csv")
    def export_table(body: dict = Body(...)) -> Response:
        """The result table as CSV, with formula-like cells protected; the API keeps the raw values."""
        fingerprint, executed, _ = executed_plan(body)
        header, rows = exports.table_rows(executed)
        return csv_response(fingerprint, "table", header, rows)

    @app.post("/api/plans/drilldown.csv")
    def export_drilldown(body: dict = Body(...)) -> Response:
        """A drilldown as CSV, with formula-like cells protected; the API keeps the raw values."""
        fingerprint, _, _, listed = listing(body)
        header, rows = exports.drilldown_csv_rows(listed)
        return csv_response(fingerprint, "source-rows", header, rows)

    @app.post("/api/plans/propose")
    def propose_plan(body: dict = Body(...)) -> dict:
        """Ask the provider for a plan; the release-one null provider proposes none, and any plan is validated first."""
        fingerprint = state.active_fingerprint
        question = body.get("question")
        if not isinstance(question, str) or not question.strip():
            raise HTTPException(
                status_code=422,
                detail={"code": "question_required", "field": "question", "message": "give a question in words"},
            )
        proposal = state.provider.propose(question)
        validation = None
        if proposal.plan is not None:
            validation = validate_plan({"plan": proposal.plan})
        return {
            "provider": state.provider.payload(),
            "plan": proposal.plan if validation and validation["valid"] else None,
            "validation": validation,
            "message": proposal.message,
            **context(fingerprint),
        }

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

    @app.get("/api/overview/value-context")
    def value_context_view(query: dict = Depends(filter_query)) -> dict:
        """The three BBD figures, each a registry metric under the filters, and the analyst-reviewed alternative."""
        fingerprint = state.active_fingerprint
        filters = active_filters(fingerprint, query)
        results = {figure.metric_id: evaluate(fingerprint, figure.metric_id, filters) for figure in value_context.FIGURES}
        replaced_rows = state.review.replaced_rows(fingerprint)
        reviewed = evaluate(fingerprint, value_context.REVIEWED.metric_id, filters) if replaced_rows else None
        return {
            **value_context.panel(
                results, reviewed, replaced_rows, lambda rows: state.store.status_counts(fingerprint, rows),
            ),
            "filters": filters.payload(),
            **context(fingerprint),
        }

    @app.get("/api/overview/claimed-hours")
    def claimed_hours_view(query: dict = Depends(filter_query), measure: str = claimed_hours.DEFAULT_MEASURE) -> dict:
        """Claimed hours (or tickets) by job under the Overview filters: a fixed Explore plan, with its request so
        the drilldown, table and exports are Explore's, and the analyst-reviewed alternative once links exist."""
        chosen = claimed_hours.MEASURE_BY_ID.get(measure)
        if chosen is None:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "unknown_measure", "field": "measure",
                    "message": f"no measure {measure!r}; measures: " + ", ".join(claimed_hours.MEASURE_BY_ID),
                },
            )
        fingerprint = state.active_fingerprint
        inheritance = plans.overview_inherited(query)
        main = overview_plan(claimed_hours.plan(chosen.metric_id), inheritance)
        replaced = state.review.replaced_rows(fingerprint)
        reviewed = None
        if replaced and chosen.reviewed_metric_id:
            reviewed = {
                "label": claimed_hours.REVIEWED_LABEL,
                "note": claimed_hours.REVIEWED_NOTE,
                "replaced_tickets": len(replaced),
                **overview_plan(claimed_hours.plan(chosen.reviewed_metric_id), inheritance),
            }
        return {
            "title": chosen.title,
            "question": claimed_hours.QUESTION,
            "note": claimed_hours.NOTE,
            "measure": chosen.id,
            "measures": [item.payload() for item in claimed_hours.MEASURES],
            **main,
            "reviewed": reviewed,
            "filters": main["result"]["filters"],
            **context(fingerprint),
        }

    @app.get("/api/overview/submission-timing")
    def submission_timing_view(query: dict = Depends(filter_query)) -> dict:
        """Weekly submissions stacked by current status, and the lag and approval-interval distributions, each
        built from Explore plans under the Overview filters and served with its request for drilldowns."""
        fingerprint = state.active_fingerprint
        inheritance = plans.overview_inherited(query)
        series = [
            {"status": status, **overview_plan(timing.weekly_plan(status), inheritance)} for status in timing.STATUSES
        ]
        every = overview_plan(timing.weekly_plan(None), inheritance)
        return {
            "question": timing.QUESTION,
            "weekly": timing.weekly(series, every),
            "lag": {
                "title": timing.LAG_TITLE, "note": timing.LAG_NOTE,
                **overview_plan(timing.distribution_plan("submission_lag_days"), inheritance),
            },
            "interval": {
                "title": timing.INTERVAL_TITLE, "note": timing.INTERVAL_NOTE,
                **overview_plan(timing.distribution_plan("observed_approval_interval_hours"), inheritance),
            },
            "filters": every["result"]["filters"],
            **context(fingerprint),
        }

    @app.get("/api/overview/data-readiness")
    def data_readiness_view(
        query: dict = Depends(filter_query), window_from: dt.date | None = None, window_to: dt.date | None = None,
    ) -> dict:
        """The readiness counts under the filters and reporting window, each from the registry or the Alias proposals."""
        fingerprint = state.active_fingerprint
        filters = active_filters(fingerprint, query)
        window = reporting_window(fingerprint, window_from, window_to)
        checks = []
        for check in data_readiness.CHECKS:
            if check.metric_id is None:
                checks.append(data_readiness.summary_item(check, None, len(unresolved_aliases(fingerprint, filters)), None))
            elif check.id in data_readiness.SUMMARISED:
                result, rows = readiness_rows(fingerprint, filters, check, window)
                checks.append(data_readiness.summary_item(check, result, None, data_readiness.summary(check, rows)))
            else:
                result = evaluate(fingerprint, check.metric_id, filters, window=window_bounds(window))
                checks.append(data_readiness.summary_item(check, result, None, None))
        return {
            "title": data_readiness.TITLE,
            "question": data_readiness.QUESTION,
            "note": data_readiness.NOTE,
            "checks": checks,
            "reporting_window": window.payload() if window else None,
            "filters": filters.payload(),
            **context(fingerprint),
        }

    @app.get("/api/overview/data-readiness/{check_id}")
    def data_readiness_drilldown(
        check_id: str,
        query: dict = Depends(filter_query),
        window_from: dt.date | None = None,
        window_to: dt.date | None = None,
    ) -> dict:
        """Exactly the rows one readiness count counts, under the same filters, window and Snapshot."""
        check = data_readiness.CHECK_BY_ID.get(check_id)
        if check is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "unknown_check", "field": "check_id",
                    "message": f"no readiness check {check_id!r}; checks: "
                    + ", ".join(item.id for item in data_readiness.CHECKS),
                },
            )
        fingerprint = state.active_fingerprint
        filters = active_filters(fingerprint, query)
        window = reporting_window(fingerprint, window_from, window_to)
        result, rows = readiness_rows(fingerprint, filters, check, window)
        return {
            "check": data_readiness.summary_item(
                check, result, len(rows) if result is None else None, data_readiness.summary(check, rows),
            ),
            "count": len(rows),
            "rows": rows,
            "reporting_window": window.payload() if window else None,
            "filters": filters.payload(),
            **context(fingerprint),
        }

    @app.get("/api/review-priorities")
    def review_priorities(
        query: dict = Depends(filter_query),
        pattern: list[str] = Query(default=[]),
        source_state: list[str] = Query(default=[]),
    ) -> dict:
        """The ranked possible duplicates under the global and pattern filters, beside the pattern matrix."""
        fingerprint = state.active_fingerprint
        filters = active_filters(fingerprint, query)
        try:
            selection = pattern_matrix.PatternFilter.build(patterns=pattern, source_states=source_state)
        except FilterError as error:
            raise HTTPException(status_code=422, detail=error.payload()) from error
        saved = state.review.outcomes(fingerprint)
        settled = state.review.settled_pairs(fingerprint)
        by_pattern = pattern_matrix.review_priorities(
            state.store.possible_duplicates(fingerprint, filters, settled), selection,
        )
        return {
            **by_pattern,
            "possible_duplicates": [with_outcomes(fingerprint, item, saved) for item in by_pattern["possible_duplicates"]],
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
