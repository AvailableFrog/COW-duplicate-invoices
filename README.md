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
The header shows the Snapshot fingerprint (SHA-256 of the workbook), the sheet name, the row and field counts, the import issues, and the analytical as-of date, which is labelled as an assumption and can be changed there.
Below it, the filter bar (date basis and range, job, status, Clear) narrows every number, and the active filters and aggregation grain are shown under it.
The Overview opens with four tiles from the metric registry: source records, Recorded Markers, Pending, and Approved/not-Keyed. They overlap conceptually and do not sum to the population.

Options:

| Option | Default | Meaning |
|---|---|---|
| `--port N` | `8765` | port on loopback; `0` picks an ephemeral port and prints it |
| `--as-of YYYY-MM-DD` | `2026-10-08` | analytical as-of date; the Snapshot is never aged by today's date |
| `--data-dir PATH` | `.scratch` | where local review data will live, kept apart from the Snapshot (gitignored) |
| `--host ADDR` | `127.0.0.1` | must be a loopback address; anything else is refused |

The Snapshot tables are rebuilt in memory from the workbook on every launch.

## Import validation

Only an unreadable or missing workbook, a workbook with no data sheet, or a data sheet missing a required column (or naming a schema column twice) stops the launch, with a message naming the problem.
The data sheet is the first worksheet whose header row carries every required column; if none does, the first worksheet with any header is checked and its missing columns are named.
The required columns are Employee, Ticket Number, Job Number, Date, Time, Regular Hours, Overtime, Double Time, Job Work Pay, Approval Status, Keyed and Created.
A missing optional column still loads; the header lists the metrics, groupings, checks and displays it disables, each with a reason.

Nothing is dropped or repaired. A cell or business ID that fails validation stays in its Ticket and becomes an import issue with its Excel row, field and one of these codes:

| Code | Raised when |
|---|---|
| `blank_row` | every cell in the row is empty; the row stays a Ticket so later rows keep their numbers, and this is its only issue |
| `missing_value` | a required cell is empty or only spaces |
| `missing_business_id` | Ticket Number or ID is empty |
| `repeated_business_id` | Ticket Number (compared as written) or ID (compared as a whole number) appears on another row |
| `invalid_number` | hours, pay or Rate is not a number; Job Number or ID is not a whole number without grouping separators |
| `invalid_date` | a date column holds neither an Excel date nor ISO 8601 text; other date text is not guessed |
| `unknown_status` | Approval Status is not exactly Approved, Pending or Rejected |
| `unknown_boolean` | Keyed is not a true or false cell |
| `formula_not_evaluated` | a cell holds a formula, which is kept as text |
| `error_value` | a cell holds a spreadsheet error such as `#N/A` |

Text columns, including Time, are kept raw and not type-checked here; a numeric zero in Time stays `0`.

## Time parsing

Every Ticket's Time cell is read once at import by the interval parser; the raw cell is never altered.
Times are read in order and paired into start and end; dashes, `to`, `till`, `until`, underscores, slashes, `&`, `and`, commas, `+`, dots, colons and spaces may sit between them, so `730am 1030am _ 230pm 430pm` is two periods.
Accepted times include `7:30`, `7.30`, `7;30`, `7/30am`, `730`, `0730`, `7 30` and `7`, with `am`, `pm`, `a`, `p`, `a.m.`, `p.m.` or `12 noon`, in any case and spacing.

| Period | Reads as |
|---|---|
| both ends carry AM/PM, or one end is in 24-hour form (hour 0 or 13-23, or a leading zero) and neither carries AM/PM | a **Confident Interval** |
| any end lacks AM/PM | an **Ambiguous Interval** with one **Plausible Reading**, labelled assumed: a start from 5:00 to 11:59 is AM and one from 12:00 to 4:59 afternoon; an end is the first reading at or after the start, so an end numerically below the start is PM; an end that carries AM/PM fixes the start |
| ends before it starts | flagged `possible_overnight` when it starts at or after noon and ends before it, otherwise `reversed_endpoints`; no interval |
| zero length, or 16 hours or longer on one Date | flagged `implausible_duration`; no interval |

Intervals are half-open, so a period ending when another begins does not overlap, and Tickets are compared on the union of their intervals.
Only Confident Intervals establish overlap or separation: a comparison is `overlap` when they intersect, `separate` when every period on both Tickets is confident and they do not, `ambiguous` (comparing Plausible Readings, assumed) when an Ambiguous Interval is involved, and `undetermined` when a Ticket has a flagged period or its Time is not `confident` or `ambiguous`.

A parse result's status is `confident`, `ambiguous`, `flagged`, `unrecognized` (text that is not times, an odd number of times, or a typo such as `pn`, never guessed), `blank`, `zero_not_a_time` (a numeric 0, never midnight), `number_not_a_time`, `datetime_not_a_period` or `not_time_text`.

## API

| Request | Returns |
|---|---|
| `GET /api/snapshot` | the active Snapshot header (fingerprint, sheet, row and field counts, fields, import issues, missing optional columns, disabled features) plus the as-of date in effect and the application version |
| `POST /api/snapshot/reimport` | reads the workbook at the launch path again. Identical content keeps the same Snapshot (`"imported": false`); different content becomes a new active Snapshot beside the old one (`"imported": true`). A workbook that cannot be imported answers 422 and the active Snapshot stays. Requests from another site's page are refused |
| `GET /api/snapshots` | every Snapshot imported in this run, oldest first, with the active one marked |
| `GET /api/as-of`, `PUT /api/as-of` | the analytical as-of date in effect; `PUT {"date": "YYYY-MM-DD"}` changes it for every later response. It stays labelled as an assumption and never follows today's date. Requests from another site's page are refused |
| `GET /api/metrics` | the metric registry and its version: the thirteen PRD metrics, each with ID, label, definition, unit, grain, allowed dimensions, null treatment, date basis, exclusions, lineage and availability (`available`, `disabled` by a missing column, or `awaiting_rule` until the matching rules exist) |
| `GET /api/metrics/{metric_id}` | one metric under the filters below: its value (a count, sum, or for day and hour metrics the median with a `summary`), `percentage` with numerator and denominator where the metric is a share of `ticket_count`, `coverage` naming the Tickets left out or only partly valued and why, and `warnings`. `group_by` takes an allowed dimension (`Approval Status`, `Keyed`, `Job Number`, `Job Name`, `Supervisor`, `Occupation`); `rows=true` lists the contributing Excel rows |
| `GET /api/overview/tiles` | the four header tiles under the filters, with their definitions, the overlap note, the grain and the filter state |
| `GET /api/filters` | what the filter bar offers: date bases with their date spans, statuses and jobs with Ticket counts |
| `GET /api/snapshots/{fingerprint}/tickets/{excel_row}` | one Ticket: its Excel row, dataframe index (Excel row minus 2), sheet, its import issues, and all cells with field name, position, raw type, raw value and number format. Blank cells have raw type `blank` and a null value; a numeric zero stays `0`; booleans stay `true` or `false`; dates are ISO 8601 text with raw type `datetime`; formulas have raw type `formula` and their formula text |
| `GET /api/snapshots/{fingerprint}/tickets/{excel_row}/time` | the Ticket's Time cell as parsed: raw type and value, parser version, status, each period with its text, confidence (`confident` or `ambiguous`), interval, Plausible Reading (`assumed: true`), flags and notes, the union of its Confident Intervals, and notes on the status |
| `GET /api/snapshots/{fingerprint}/time-parses` | how every Time cell in the Snapshot parsed: Ticket counts and Excel rows by status and raw type |
| `GET /api/snapshots/{fingerprint}/time-comparison?excel_row=A&excel_row=B` | whether two Tickets' work periods overlap: `result`, `basis`, `assumed`, the `intersection` and `overlap_minutes`, an explanation, and both parse results. Exactly two rows, or 422 |

Filters are query parameters on the metric and tile requests: `date_basis` (`Created`, `Date` or `Date Approved`, default `Created`), `date_from` and `date_to` (inclusive ISO dates on that basis), and repeatable `job` and `status`.
Without a date range every metric covers all dates, so totals reconcile with the import; a Ticket whose filtered value is unusable falls outside an active filter.
A filter, metric or dimension outside the allowlist answers 422 (404 for an unknown metric) with `detail.code`, `detail.field` and `detail.message`.

Every response that carries numbers also carries `snapshot_fingerprint`, `as_of` and `versions` (`app`, `registry`, `rules`, `parser`).
The rule version stays `0.0.0` until the matching rules exist.

## Tests

The one test seam is the HTTP API of the booted application, run against the committed workbook (`docs/adr/0003`).
A refused launch never reaches HTTP, so those tests assert on the launch command's exit status and error message instead.
The fixture in `tests/conftest.py` starts the real process on an ephemeral loopback port with a temporary data directory.
Import-validation tests that need shapes the export does not have build a minimal same-schema workbook at test time with `tests/synthetic.py`.

```sh
uv run pytest                             # API tests
npm --prefix frontend run typecheck       # TypeScript
```

One test is skipped until the frontend has been built.

## Layout

```
src/labour_ticket_analytics/   cli (launch), workbook (import), schema (columns), validation (import issues), normalized (Ticket values for metrics),
                               metrics (registry), filters (filter bar), timeparse (interval parser), versions, store (DuckDB Snapshot tables), api (HTTP)
frontend/                      React + TypeScript shell built with Vite into frontend/dist
tests/                         API tests at the booted-app seam
data/                          the committed source workbook (private repository, ADR 0003)
docs/                          PRD, decision log, ADRs, handoff sources
```
