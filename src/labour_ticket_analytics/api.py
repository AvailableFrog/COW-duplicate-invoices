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
from labour_ticket_analytics.filters import DEFAULT_DATE_BASIS, FilterError, Filters
from labour_ticket_analytics.metrics import METRICS, MetricError, registry_payload
from labour_ticket_analytics.store import SnapshotStore
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
    ("ticket_count", "Source records"),
    ("marked_ticket_count", "Recorded Markers"),
    ("pending_count", "Pending"),
    ("approved_not_keyed_count", "Approved, not Keyed"),
)
TILES_OVERLAP_NOTE = (
    "These tiles overlap conceptually and do not sum to the source records: each counts Tickets "
    "from the same population, and one Ticket can fall under more than one tile."
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
    frontend_dist: Path = FRONTEND_DIST
    import_lock: threading.Lock = field(default_factory=threading.Lock)

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
                added = self.store.add_snapshot(snapshot)
                fingerprint = snapshot.fingerprint
            self.active_fingerprint = fingerprint
            return added


class AsOfChange(BaseModel):
    date: dt.date


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

    def evaluate(fingerprint: str, metric_id: str, filters: Filters, **options) -> dict:
        metric = METRICS.get(metric_id)
        if metric is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "unknown_metric", "field": "metric_id", "message": f"no metric {metric_id!r} in the registry"},
            )
        try:
            return state.store.evaluate_metric(fingerprint, metric, filters, state.as_of, **options)
        except MetricError as error:
            raise HTTPException(status_code=422, detail=error.payload()) from error

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

    @app.get("/api/filters")
    def filter_options() -> dict:
        fingerprint = state.active_fingerprint
        return {**state.store.filter_options(fingerprint), **context(fingerprint)}

    @app.get("/api/overview/tiles")
    def tiles(query: dict = Depends(filter_query)) -> dict:
        fingerprint = state.active_fingerprint
        filters = active_filters(fingerprint, query)
        results = [(label, evaluate(fingerprint, metric_id, filters)) for metric_id, label in TILES]
        return {
            "tiles": [
                {
                    "metric_id": result["metric"]["id"],
                    "label": label,
                    "value": result["value"],
                    "unit": result["metric"]["unit"],
                    "definition": result["metric"]["definition"],
                    "percentage": result["percentage"],
                    "warnings": result["warnings"],
                }
                for label, result in results
            ],
            "note": TILES_OVERLAP_NOTE,
            "grain": "Ticket",
            "filters": filters.payload(),
            **context(fingerprint),
        }

    @app.get("/api/snapshots/{fingerprint}/tickets/{excel_row}")
    def ticket(fingerprint: str, excel_row: int) -> dict:
        payload = state.store.ticket(fingerprint, excel_row)
        if payload is None:
            raise HTTPException(
                status_code=404,
                detail=f"no Ticket at Excel row {excel_row} in Snapshot {fingerprint[:12]}",
            )
        return {**payload, **context(fingerprint)}

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
