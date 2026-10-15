"""Ticket #37: the 50,000-row performance run, opt-in, measured and recorded, never asserted.

PRD section 12 targets, on the documented reference machine: a 50,000-row
same-schema import in under 30 seconds and ordinary aggregations in under 2
seconds. This run generates the workbook with tests/generate.py, boots the
application on it and times the import, the Overview's first screen, filters,
drilldowns and an Explore plan. Results go to test-logs/scale-timings.json and
are kept apart from findings about the real export.

    LTA_SCALE=1 uv run pytest -s tests/test_scale.py
"""

from __future__ import annotations

import json
import os
import platform
import statistics
import sys
import time
from pathlib import Path

import pytest
from generate import generate, write_large

from conftest import REPO_ROOT, boot, shutdown

ROWS = int(os.environ.get("LTA_SCALE_ROWS", "50000"))
RESULTS = REPO_ROOT / "test-logs" / "scale-timings.json"
REPEATS = 3

pytestmark = pytest.mark.skipif(os.environ.get("LTA_SCALE") != "1", reason="opt-in: set LTA_SCALE=1")

FIRST_SCREEN = [
    "/api/snapshot", "/api/overview/tiles", "/api/review-priorities", "/api/flagged-duplicates",
    "/api/overview/processing-queue", "/api/overview/data-readiness", "/api/overview/claimed-hours",
    "/api/overview/submission-timing", "/api/overview/value-context",
]
PLAN = {
    "metric_id": "claimed_hours", "group_by": ["Supervisor"], "filters": [], "date_basis": "Created",
    "date_range": None, "chart": "bar_horizontal", "sort": "metric_desc", "limit": 10, "include_other": True,
}
ORDINARY = {
    "tiles, status filter": ("GET", "/api/overview/tiles?status=Pending", None),
    "tiles, job filter": ("GET", "/api/overview/tiles?job=40001", None),
    "tiles, Created range": ("GET", "/api/overview/tiles?date_basis=Created&date_from=2026-09-10&date_to=2026-09-20", None),
    "review priorities, status filter": ("GET", "/api/review-priorities?status=Approved", None),
    "processing-queue bucket drilldown": ("GET", "/api/metrics/pending_submission_age_days/buckets/14-29", None),
    "data-readiness drilldown": ("GET", "/api/overview/data-readiness/ambiguous_intervals", None),
    "claimed hours by job": ("GET", "/api/overview/claimed-hours", None),
    "submission timing": ("GET", "/api/overview/submission-timing", None),
    "Explore plan execute": ("POST", "/api/plans/execute", {"plan": PLAN}),
    "Explore drilldown": ("POST", "/api/plans/drilldown", {"plan": PLAN, "group": "Synthetic Supervisor A"}),
}


def timed(client, method: str, path: str, body) -> float:
    started = time.perf_counter()
    response = client.request(method, path, json=body) if body is not None else client.request(method, path)
    elapsed = time.perf_counter() - started
    assert response.status_code == 200, (path, response.status_code, response.text[:200])
    return elapsed


def test_measure_a_50000_row_import_and_ordinary_aggregations(tmp_path):
    started = time.perf_counter()
    tickets, planted = generate(ROWS, seed=1)
    workbook = write_large(tmp_path / "scale.xlsx", tickets)
    generation = time.perf_counter() - started

    started = time.perf_counter()
    app = boot(workbook, tmp_path / "data", timeout_seconds=120)
    listening = time.perf_counter() - started
    try:
        assert app.get("/api/snapshot").json()["snapshot"]["row_count"] == ROWS
        first_screen = sum(timed(app.client, "GET", path, None) for path in FIRST_SCREEN)
        ordinary = {}
        for label, request in ORDINARY.items():
            samples = [timed(app.client, *request) for _ in range(REPEATS)]
            ordinary[label] = {
                "first_seconds": round(samples[0], 3),
                "median_seconds": round(statistics.median(samples), 3),
                "max_seconds": round(max(samples), 3),
            }
        possible_duplicates = len(app.get("/api/review-priorities").json()["possible_duplicates"])
    finally:
        shutdown(app)

    results = {
        "rows": ROWS,
        "seed": 1,
        "environment": {
            "python": sys.version.split()[0], "platform": platform.platform(), "processor_count": os.cpu_count(),
        },
        "generate_and_write_seconds": round(generation, 2),
        "import": {"launch_to_listening_seconds": round(listening, 2), "target_seconds": 30},
        "first_screen_requests_seconds": round(first_screen, 2),
        "ordinary_responses": ordinary,
        "ordinary_target_seconds": 2,
        "possible_duplicates": possible_duplicates,
        "planted_pairs": len(planted),
    }
    RESULTS.parent.mkdir(exist_ok=True)
    RESULTS.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")

    print(f"\n{ROWS} rows: generated in {generation:.1f}s; launch to listening {listening:.1f}s (target 30s); "
          f"first screen {first_screen:.2f}s")
    for label, numbers in ordinary.items():
        print(f"{label}: median {numbers['median_seconds']}s, max {numbers['max_seconds']}s (target 2s)")
    # The background is built so only the planted pairs can be linked, at any size.
    assert possible_duplicates == len(planted)
