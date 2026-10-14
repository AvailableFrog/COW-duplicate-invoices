"""The one test seam for release one: the HTTP API of the booted application.

A session-scoped fixture starts the real process on an ephemeral loopback port
against the committed workbook, with a temporary data directory for local
review data, and tests make HTTP requests and assert on JSON.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKBOOK = REPO_ROOT / "data" / "Labour Tickets Export.xlsx"
LISTENING_PREFIX = "Listening on "

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


@pytest.fixture(scope="session")
def app() -> BootedApp:
    with tempfile.TemporaryDirectory(prefix="lta-review-") as data_dir:
        booted = boot(WORKBOOK, Path(data_dir))
        try:
            yield booted
        finally:
            shutdown(booted)
