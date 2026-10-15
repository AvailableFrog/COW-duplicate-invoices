"""Ticket #18: measured load and response times, printed and recorded, never asserted.

PRD section 12 sets targets on the documented reference machine: first
workbook load under 10 seconds, ordinary filter and drilldown responses under
1 second. Timings depend on the machine, so this test measures them and writes
them to test-logs/api-timings.json for the test report; it fails only if a
request fails, never on a slow number.
"""

from __future__ import annotations

import json
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path

from conftest import REPO_ROOT, WORKBOOK, boot, shutdown

RESULTS = REPO_ROOT / "test-logs" / "api-timings.json"
REPEATS = 5
FINGERPRINT = "36378ee04717f2432b9ec7e3a999d484da7dd8de43ff51869ba88a68047004fb"

# The requests the Overview makes when it first opens.
FIRST_SCREEN = [
    ("GET", "/api/snapshot", None),
    ("GET", "/api/overview/tiles", None),
    ("GET", "/api/review-priorities", None),
    ("GET", "/api/flagged-duplicates", None),
    ("GET", "/api/overview/processing-queue", None),
    ("GET", "/api/overview/data-readiness", None),
    ("GET", "/api/overview/value-context", None),
]
PENDING_BY_SUPERVISOR = {
    "metric_id": "ticket_count", "group_by": ["Supervisor"],
    "filters": [{"field": "Approval Status", "operator": "eq", "value": "Pending"}],
    "date_basis": "Created", "date_range": None, "chart": "bar_horizontal", "sort": "metric_desc",
    "limit": 10, "include_other": True,
}
# Ordinary filter and drilldown requests, each timed REPEATS times.
ORDINARY = {
    "tiles, status filter": ("GET", "/api/overview/tiles?status=Pending", None),
    "tiles, job filter": ("GET", "/api/overview/tiles?job=41215", None),
    "tiles, Created range": ("GET", "/api/overview/tiles?date_basis=Created&date_from=2026-09-15&date_to=2026-09-30", None),
    "review priorities, status filter": ("GET", "/api/review-priorities?status=Approved", None),
    "pattern-matrix cell drilldown": ("GET", "/api/review-priorities?pattern=same_claim_twice&source_state=approved_keyed", None),
    "processing-queue bucket drilldown": ("GET", "/api/metrics/pending_submission_age_days/buckets/7-13", None),
    "data-readiness drilldown": ("GET", "/api/overview/data-readiness/ambiguous_intervals", None),
    "evidence drawer (C)": ("GET", f"/api/snapshots/{FINGERPRINT}/tickets/620/possible-duplicate", None),
    "Explore plan execute": ("POST", "/api/plans/execute", {"plan": PENDING_BY_SUPERVISOR}),
    "Explore bar drilldown": ("POST", "/api/plans/drilldown", {"plan": PENDING_BY_SUPERVISOR, "group": "Bradford Goodluck"}),
}


def timed(client, method: str, path: str, body) -> float:
    started = time.perf_counter()
    response = client.request(method, path, json=body) if body is not None else client.request(method, path)
    elapsed = time.perf_counter() - started
    assert response.status_code == 200, (path, response.status_code, response.text[:200])
    return elapsed


def test_measure_first_load_and_ordinary_response_times():
    with tempfile.TemporaryDirectory(prefix="lta-timing-") as data_dir:
        started = time.perf_counter()
        app = boot(WORKBOOK, Path(data_dir))
        listening = time.perf_counter() - started
        try:
            first_screen = sum(timed(app.client, *request) for request in FIRST_SCREEN)
            ordinary = {}
            for label, request in ORDINARY.items():
                samples = [timed(app.client, *request) for _ in range(REPEATS)]
                # The first call can fill the result cache; report it apart from the warm median.
                ordinary[label] = {
                    "first_seconds": round(samples[0], 3),
                    "median_seconds": round(statistics.median(samples), 3),
                    "max_seconds": round(max(samples), 3),
                }
        finally:
            shutdown(app)

    results = {
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor_count": __import__("os").cpu_count(),
        },
        "first_load": {
            "launch_to_listening_seconds": round(listening, 3),
            "first_screen_requests_seconds": round(first_screen, 3),
            "total_seconds": round(listening + first_screen, 3),
            "target_seconds": 10,
        },
        "ordinary_responses": ordinary,
        "ordinary_target_seconds": 1,
        "repeats": REPEATS,
    }
    RESULTS.parent.mkdir(exist_ok=True)
    RESULTS.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")

    print(f"\nfirst load: {results['first_load']['total_seconds']}s (launch {listening:.2f}s + first screen {first_screen:.2f}s); target 10s")
    for label, numbers in ordinary.items():
        print(f"{label}: first {numbers['first_seconds']}s, median {numbers['median_seconds']}s, max {numbers['max_seconds']}s; target 1s")
    assert len(ordinary) == len(ORDINARY)
