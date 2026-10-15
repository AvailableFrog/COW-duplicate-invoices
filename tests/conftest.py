"""The one test seam for release one: the HTTP API of the booted application.

A session-scoped fixture starts the real process on an ephemeral loopback port
against the committed workbook, with a temporary data directory for local
review data, and tests make HTTP requests and assert on JSON.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKBOOK = REPO_ROOT / "data" / "Labour Tickets Export.xlsx"
LISTENING_PREFIX = "Listening on "
# Everything the booted services print during a run, checked for source data when the run ends.
SERVICE_LOG = REPO_ROOT / "test-logs" / "pytest-service.log"
_log_lock = threading.Lock()


def _record(lines: list[str]) -> None:
    with _log_lock, SERVICE_LOG.open("a", encoding="utf-8") as log:
        log.writelines(lines)


def _drain(stream) -> None:
    """Keep reading a service's output into the run log, so its pipe never fills."""
    for line in stream:
        _record([line])


def pytest_sessionstart(session: pytest.Session) -> None:
    SERVICE_LOG.parent.mkdir(exist_ok=True)
    SERVICE_LOG.write_text("", encoding="utf-8")


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Fail the run if any service printed an employee name, email or description."""
    from log_check import leaks

    hits = leaks(SERVICE_LOG.read_text(encoding="utf-8"))
    lines = len(SERVICE_LOG.read_text(encoding="utf-8").splitlines())
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    message = (
        f"service logs: {len(hits)} sensitive value(s) found in {lines} lines of {SERVICE_LOG.relative_to(REPO_ROOT)}"
        if hits
        else f"service logs: no employee names, emails or descriptions in {lines} lines of {SERVICE_LOG.relative_to(REPO_ROOT)}"
    )
    if reporter is not None:
        reporter.ensure_newline()
        reporter.write_line(message)
    if hits:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED

# Published in docs/source/handoff-README.md under "Integrity".
HANDOFF_WORKBOOK_SHA256 = "36378ee04717f2432b9ec7e3a999d484da7dd8de43ff51869ba88a68047004fb"


@dataclass
class BootedApp:
    base_url: str
    process: subprocess.Popen
    client: httpx.Client

    def get(self, path: str, **kwargs) -> httpx.Response:
        return self.client.get(path, **kwargs)


def launch_command(workbook: Path, *extra: str) -> list[str]:
    return [sys.executable, "-m", "labour_ticket_analytics", str(workbook), *extra]


def boot(workbook: Path, data_dir: Path, *extra: str, timeout_seconds: float = 60.0) -> BootedApp:
    process = subprocess.Popen(
        launch_command(workbook, "--port", "0", "--data-dir", str(data_dir), *extra),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=REPO_ROOT,
    )
    assert process.stdout is not None
    lines: list[str] = []
    while True:
        line = process.stdout.readline()
        if line == "" and process.poll() is not None:
            process.wait()
            raise RuntimeError("application exited before listening:\n" + "".join(lines))
        lines.append(line)
        if line.startswith(LISTENING_PREFIX):
            base_url = line[len(LISTENING_PREFIX):].strip()
            break
    _record(lines)
    threading.Thread(target=_drain, args=(process.stdout,), daemon=True).start()
    client = httpx.Client(base_url=base_url, timeout=timeout_seconds)
    return BootedApp(base_url=base_url, process=process, client=client)


def shutdown(app: BootedApp) -> None:
    app.client.close()
    app.process.terminate()
    try:
        app.process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        app.process.kill()
        app.process.wait()


@contextmanager
def running(workbook: Path, data_dir: Path, *extra: str):
    """Boot the application for the duration of a with-block."""
    booted = boot(workbook, data_dir, *extra)
    try:
        yield booted
    finally:
        shutdown(booted)


@pytest.fixture(scope="session")
def app() -> BootedApp:
    with tempfile.TemporaryDirectory(prefix="lta-review-") as data_dir:
        booted = boot(WORKBOOK, Path(data_dir))
        try:
            yield booted
        finally:
            shutdown(booted)
