"""The local HTTP JSON API and the built frontend, served from one port."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from labour_ticket_analytics import __version__
from labour_ticket_analytics.store import SnapshotStore

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
    frontend_dist: Path = FRONTEND_DIST


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
            candidate = (state.frontend_dist / path).resolve()
            if path and candidate.is_file() and state.frontend_dist.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(index_html)

    else:

        @app.get("/", include_in_schema=False)
        def missing_frontend() -> HTMLResponse:
            return HTMLResponse(MISSING_FRONTEND_HTML)

    return app
