"""Ticket #2: one launch command, loopback only, frontend and API on one port."""

import subprocess
from pathlib import Path

import pytest

from conftest import REPO_ROOT, WORKBOOK, boot, launch_command, shutdown

FRONTEND_INDEX = REPO_ROOT / "frontend" / "dist" / "index.html"


def run_launch(*args: str, workbook: Path = WORKBOOK) -> subprocess.CompletedProcess:
    return subprocess.run(launch_command(workbook, *args), capture_output=True, text=True, timeout=60, cwd=REPO_ROOT)


def test_listens_on_loopback(app):
    assert app.base_url.startswith("http://127.0.0.1:")


def test_refuses_to_bind_to_a_non_loopback_address():
    result = run_launch("--host", "0.0.0.0", "--port", "0")

    assert result.returncode == 2
    assert "loopback" in result.stderr
    assert "Listening on" not in result.stdout


def test_missing_workbook_is_refused_with_a_specific_message(tmp_path):
    result = run_launch("--port", "0", "--data-dir", str(tmp_path), workbook=tmp_path / "nowhere.xlsx")

    assert result.returncode == 2
    assert "nowhere.xlsx" in result.stderr


def test_as_of_date_can_be_set_at_launch(tmp_path):
    booted = boot(WORKBOOK, tmp_path, "--as-of", "2026-10-01")
    try:
        body = booted.get("/api/snapshot").json()
    finally:
        shutdown(booted)

    assert body["as_of"] == {**body["as_of"], "date": "2026-10-01", "is_assumption": True}


def test_unknown_api_path_is_a_json_not_found_not_the_frontend(app):
    response = app.get("/api/no-such-thing")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


def test_root_serves_html_from_the_same_port(app):
    response = app.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


@pytest.mark.skipif(not FRONTEND_INDEX.is_file(), reason="frontend not built (npm --prefix frontend run build)")
def test_root_serves_the_built_frontend(app):
    response = app.get("/")

    assert response.text == FRONTEND_INDEX.read_text()
    assert '<div id="root">' in response.text
