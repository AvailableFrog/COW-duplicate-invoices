# Labour Ticket Analytics

A small, local-first application for reviewing a C.O. Williams labour-ticket export.
It imports one workbook as an immutable Snapshot, binds to loopback only, and serves a JSON API and a React frontend from one port.
Nothing is ever written back to the workbook.
Vocabulary follows `GLOSSARY.md`; the product is specified in `docs/prd.md` and the ADRs under `docs/adr/`.

## Requirements

| Tool | Version | Used for |
|---|---|---|
| Python | 3.13 | the service (`pyproject.toml` pins every package) |
| [uv](https://docs.astral.sh/uv/) | 0.11 | creating the virtual environment from `uv.lock` |
| Node.js | 22 | building the frontend once (`frontend/package-lock.json` pins every package) |

`pip` works instead of uv: `python -m venv .venv && .venv/bin/pip install -e . --group dev` (pip 25.1 or newer; with older pip run `pip install -e .` and then `pip install pytest==9.1.1 httpx==0.28.1`).

## Set up once

```sh
uv sync                                   # Python environment with pinned versions
npm --prefix frontend ci                  # frontend dependencies with pinned versions
npm --prefix frontend run build           # builds frontend/dist, served by the Python process
```

## Launch

```sh
uv run labour-ticket-analytics "data/Labour Tickets Export.xlsx"
```

Then open the printed address, by default `http://127.0.0.1:8765`.
The header shows the Snapshot fingerprint (SHA-256 of the workbook), the sheet name, the row and field counts, the import issues, and the analytical as-of date, which is labelled as an assumption.

Options:

| Option | Default | Meaning |
|---|---|---|
| `--port N` | `8765` | port on loopback; `0` picks an ephemeral port and prints it |
| `--as-of YYYY-MM-DD` | `2026-10-08` | analytical as-of date; the Snapshot is never aged by today's date |
| `--data-dir PATH` | `.scratch` | where local review data will live, kept apart from the Snapshot (gitignored) |
| `--host ADDR` | `127.0.0.1` | must be a loopback address; anything else is refused |

The Snapshot tables are rebuilt in memory from the workbook on every launch.
A workbook that cannot be read, or is not found, stops the launch with a message naming the problem.

## API

| Request | Returns |
|---|---|
| `GET /api/snapshot` | the active Snapshot header (fingerprint, sheet, row and field counts, fields, import issues) plus the as-of date in effect and the application version |
| `GET /api/snapshots/{fingerprint}/tickets/{excel_row}` | one Ticket: its Excel row, dataframe index (Excel row minus 2), sheet, and all cells with field name, position, raw type, raw value and number format. Blank cells have raw type `blank` and a null value; a numeric zero stays `0`; booleans stay `true` or `false`; dates are ISO 8601 text with raw type `datetime` |

## Tests

The one test seam is the HTTP API of the booted application, run against the committed workbook (`docs/adr/0003`).
The fixture in `tests/conftest.py` starts the real process on an ephemeral loopback port with a temporary data directory.

```sh
uv run pytest                             # API tests
npm --prefix frontend run typecheck       # TypeScript
```

One test is skipped until the frontend has been built.

## Layout

```
src/labour_ticket_analytics/   cli (launch), workbook (import), store (DuckDB Snapshot tables), api (HTTP)
frontend/                      React + TypeScript shell built with Vite into frontend/dist
tests/                         API tests at the booted-app seam
data/                          the committed source workbook (private repository, ADR 0003)
docs/                          PRD, decision log, ADRs, handoff sources
```
