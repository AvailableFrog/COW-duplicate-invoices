"""The local HTTP JSON API and the built frontend, served from one port."""

from __future__ import annotations

import datetime as dt
import threading
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from labour_ticket_analytics import __version__
from labour_ticket_analytics.store import SnapshotStore
from labour_ticket_analytics.workbook import WorkbookError, fingerprint_workbook, import_workbook

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
DEFAULT_AS_OF = dt.date(2026, 10, 8)
AS_OF_NOTE = (
    "Analytical as-of date. The export carries no timestamp, so this is an assumption "
    "based on the latest Created date; it is never today's date."
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
        raise HTTPException(status_code=403, detail="cross-site requests may not change the active Snapshot")


def create_app(state: AppState) -> FastAPI:
    app = FastAPI(title="Labour Ticket Analytics", version=__version__, docs_url=None, redoc_url=None)

    def header_payload() -> dict:
        snapshot = state.store.snapshot_header(state.active_fingerprint)
        if snapshot is None:
            raise HTTPException(status_code=503, detail="no active Snapshot")
        return {
            "snapshot": snapshot,
            "as_of": {"date": state.as_of.isoformat(), "is_assumption": True, "note": AS_OF_NOTE},
            "versions": {"app": __version__},
        }

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
        return {
            "snapshots": [
                {**snapshot, "active": snapshot["fingerprint"] == state.active_fingerprint}
                for snapshot in state.store.snapshots()
            ]
        }

    @app.get("/api/snapshots/{fingerprint}/tickets/{excel_row}")
    def ticket(fingerprint: str, excel_row: int) -> dict:
        payload = state.store.ticket(fingerprint, excel_row)
        if payload is None:
            raise HTTPException(
                status_code=404,
                detail=f"no Ticket at Excel row {excel_row} in Snapshot {fingerprint[:12]}",
            )
        return payload

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
