"""The single launch command.

    labour-ticket-analytics "data/Labour Tickets Export.xlsx" [--port N] [--as-of YYYY-MM-DD] [--data-dir PATH]

Imports the workbook as a Snapshot, opens the local review file in the data
directory, binds to loopback only, and serves the API and the built frontend
from the same port. Port 0 picks an ephemeral port; the
address actually in use is printed as "Listening on http://127.0.0.1:PORT".
"""

from __future__ import annotations

import argparse
import datetime as dt
import ipaddress
import socket
import sys
import time
from pathlib import Path

import uvicorn

from labour_ticket_analytics.api import DEFAULT_AS_OF, AppState, create_app
from labour_ticket_analytics.review import ReviewStore, ReviewStoreInUse
from labour_ticket_analytics.store import SnapshotStore
from labour_ticket_analytics.workbook import WorkbookError, import_workbook

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_DATA_DIR = Path(".scratch")
LOOPBACK_NAMES = {"localhost"}


class LaunchError(Exception):
    pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="labour-ticket-analytics",
        description="Import a labour-ticket workbook as a Snapshot and serve the review application on loopback.",
    )
    parser.add_argument("workbook", type=Path, help="path to the .xlsx export")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port on loopback (0 = ephemeral; default {DEFAULT_PORT})")
    parser.add_argument("--host", default=DEFAULT_HOST, help="loopback address to bind; anything else is refused")
    parser.add_argument("--as-of", type=dt.date.fromisoformat, default=DEFAULT_AS_OF, help=f"analytical as-of date (default {DEFAULT_AS_OF.isoformat()}, an assumption)")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="directory for local review data, kept apart from the Snapshot")
    return parser.parse_args(argv)


def is_loopback(host: str) -> bool:
    if host in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def require_loopback(host: str) -> None:
    if not is_loopback(host):
        raise LaunchError(f"refusing to bind to {host!r}: this service binds to loopback only")


def bind(host: str, port: int) -> socket.socket:
    sock = socket.create_server((host, port), backlog=128)
    sock.set_inheritable(True)
    return sock


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        require_loopback(args.host)
        started = time.perf_counter()
        snapshot = import_workbook(args.workbook)
        store = SnapshotStore()
        store.add_snapshot(snapshot)
        elapsed = time.perf_counter() - started
        review = ReviewStore.in_data_dir(args.data_dir)
    except (LaunchError, WorkbookError, ReviewStoreInUse) as error:
        print(f"error: {error}", file=sys.stderr, flush=True)
        return 2
    print(
        f"Imported {snapshot.workbook_name} as Snapshot {snapshot.fingerprint[:12]}: "
        f"{snapshot.row_count} rows, {snapshot.field_count} fields, "
        f"{len(snapshot.import_issues)} import issues, {elapsed:.2f}s",
        flush=True,
    )
    state = AppState(
        store=store,
        active_fingerprint=snapshot.fingerprint,
        as_of=args.as_of,
        workbook_path=args.workbook.resolve(),
        review=review,
    )
    app = create_app(state)
    try:
        sock = bind(args.host, args.port)
        bound_host, bound_port = sock.getsockname()[:2]
        url_host = f"[{bound_host}]" if ":" in bound_host else bound_host
        print(f"Local review data: {review.path.resolve()}", flush=True)
        print(f"Listening on http://{url_host}:{bound_port}", flush=True)
        config = uvicorn.Config(app, host=bound_host, port=bound_port, log_level="warning", access_log=False)
        uvicorn.Server(config).run(sockets=[sock])
    finally:
        review.close()
    return 0
