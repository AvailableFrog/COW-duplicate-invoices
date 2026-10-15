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
The Overview opens with five tiles from the metric registry: source records, flagged duplicates, exact repeats not flagged (possible duplicates, with their ticket count shown), Pending, and Approved/not-Keyed. They overlap conceptually and do not sum to the population.
Below the tiles, Review priorities lists every possible duplicate the matching rules found, ranked for review, under a pattern-by-source-state count matrix and a multi-label pattern filter, described under [Patterns and source states](#patterns-and-source-states).
Opening one (each name is a button, reachable by Tab and Enter) shows its evidence drawer, described under [Evidence drawer](#evidence-drawer).
Further down, Flagged duplicates lists the flagged tickets, the [Processing queue](#processing-queue) charts how old the Pending and Approved/not-Keyed submissions are, and [Data readiness](#data-readiness) counts the records that cannot be reliably compared or valued.
At the foot of the Overview, the collapsed [Value context](#value-context) panel gives three small BBD figures with their formulas and completeness.

Options:

| Option | Default | Meaning |
|---|---|---|
| `--port N` | `8765` | port on loopback; `0` picks an ephemeral port and prints it |
| `--as-of YYYY-MM-DD` | `2026-10-08` | analytical as-of date; the Snapshot is never aged by today's date |
| `--data-dir PATH` | `.scratch` | where the local review file `review.duckdb` lives, apart from the Snapshot (gitignored); one running copy per directory |
| `--host ADDR` | `127.0.0.1` | must be a loopback address; anything else is refused |

The Snapshot tables are rebuilt in memory from the workbook on every launch.
Review Outcomes, kept/replaced links and their history persist across launches in `review.duckdb` in the data directory, described under [Review outcomes](#review-outcomes).

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

## Matching rules

The rules run over normalized Ticket values when a Snapshot is imported and store each match as a **Candidate** between two Tickets, with the rule ID, the fields compared, the evidence strength, the pattern and a reason.
Strength describes the matching evidence, never whether anyone was paid.
Rules only compare Tickets in one search space: the same Date as recorded, and employee labels (trimmed, case-folded, spaces collapsed) that are the same, differ only in spacing, or are joined by a confirmed Alias. The search space is never a rule: two Tickets are not linked because their hours match on the same day. Each rule says which employee relation it accepts: the Name-space variant compares labels that differ only in spacing, the Work-period conflict, Flagged-duplicate counterpart and Repeated component accept one label or a confirmed Alias, and every other rule compares one label only.

| Rule | Matches when | Strength | Pattern |
|---|---|---|---|
| `strict_repeat` | Employee, Date as recorded, Job Number, Time (text trimmed, case-folded, spaces collapsed; a typed cell compares by its type and value, so the number 0 matches only another 0) and Regular Hours, Overtime, Double Time and Job Work Pay are all equal | strong | Same claim appears twice |
| `time_text_variant` | Job Number and all four claim components equal, Time differs after that normalization but every period on both reads as the same Confident Intervals, or the same runs of digits and letters differ only in spacing, case or punctuation; the reason names which | moderate | Same claim looks different as text |
| `name_space_variant` | the employee labels differ but are equal once every space is removed (case already folded), and Date, Job Number, Time (normalized as above) and all four claim components are equal. It proposes an Alias and is a Candidate itself; it never merges the labels, reads the same whether the Alias is proposed, confirmed or rejected, and never reads Email | moderate | Same claim looks different as text |
| `work_period_conflict` | the same employee label or two labels joined by a confirmed Alias, and the two Tickets' Confident Intervals intersect (half-open, union against union); jobs and claim components may differ. A conflicting work claim, not proof of a repeated whole ticket | moderate | Possible correction or resubmission; the repeat's own pattern when the pair also matches the Strict repeat, Time-text variant or Name-space variant |
| `ambiguous_period_comparison` | same nonzero Job Number and all four claim components, distinct Time whose comparison is ambiguous (an Ambiguous Interval and no confident overlap); the reason gives the assumed overlap, if any, labelled assumed and never asserted | weak | Equal duration, separate periods; Possible correction or resubmission when the assumed readings would overlap |
| `flagged_duplicate_counterpart` | at least one Ticket is a flagged duplicate (Approved, Job Number 0); one label or a confirmed Alias; and either all four claim components equal, the same Confident Intervals (every period confident on both), or the same nonempty Time text (normalized as above) that does not read confidently together with the same nonempty description text (trimmed, case-folded, spaces collapsed). Job Number is never compared and no job is recovered from Job Name; every plausible counterpart gets its own Candidate and none is chosen as the original | moderate; weak for an **uncertain counterpart** found only through the Time text and description (K) | Possible correction or resubmission; the repeat's own pattern when the pair also matches a repeat rule |
| `repeated_component` | one label or a confirmed Alias, equal positive Job Work Pay, and the same nonzero Job Number or Job Number 0 on at least one Ticket. A low-confidence component comparison of one payment component, never the whole claim | weak | Repeated payment component |

A blank or invalid comparison field never satisfies equality. ID, Ticket Number, timestamps and Supervisor are never compared, and description only by the Flagged-duplicate counterpart's uncertain path; they stay review evidence.
Rejected Tickets take part like any other.
A pair several rules match keeps one Candidate per rule, each with its reason, and still has one Review Outcome.
The search space is defined in one place (`in_search_space` and `employee_relation` in `rules.py`), and each rule's `accepts_alias` says whether a confirmed Alias widens it: the Work-period conflict, Flagged-duplicate counterpart and Repeated component do. A confirmed Alias joins exactly its two labels, on every date, and the employee-label count still counts both; see [Aliases](#aliases).

**Possible duplicates** are the connected components of Candidate edges within one employee-and-date context, recomposed from the Candidates on every request.
Every edge stays visible; Tickets joined only through another Ticket need not repeat each other, which a possible duplicate of three or more says in its reason, and no Ticket is ever called redundant.
Each is named from its sorted member ticket numbers, for example "Possible duplicate L225526+L225761"; the name is for reading aloud, never a storage key (`docs/adr/0004`).

Review priorities ranks them in four tiers, then by the oldest Created among the members, then by the lowest Ticket Number:

| Tier | Holds |
|---|---|
| 1 | exact repeats, not flagged: a strict match with every ticket Approved and Keyed and none a flagged duplicate |
| 2 | an Approved ticket beside a Pending or not-Keyed one, or Approved and Keyed tickets linked by a weaker rule, with nothing Rejected or flagged |
| 3 | Pending conflicts, and anything holding a flagged duplicate whose counterpart is unresolved |
| 4 | anything holding a Rejected ticket or an unreadable status, or a flagged duplicate whose every counterpart relationship a reviewer settled |

A flagged duplicate's counterpart is **settled** only when a Flagged-duplicate counterpart Candidate links it to a Ticket and a reviewer saved Confirmed duplicate or Replacement ticket on that pair, or linked the two as kept and replaced (decision-log entry 54). A counterpart nobody reviewed, Not a duplicate, Needs follow-up, or an outcome on a pair another rule linked leaves it unresolved, so with no review data every possible duplicate holding a flagged duplicate is in tier 3.

This is review priority, not a probability of wrongdoing; no view ranks employees or supervisors.
On the committed workbook the Strict repeat rule finds 34 two-ticket groups: C, D, E and F (rows 620/855, 974/1868, 1309/1656, 2206/2351) lead tier 1, one Approved/Pending, one Pending/Pending and 28 with a Rejected ticket.
The time-aware rules add G (82/103) as a Time-text variant, J (61/105) and B (33/79) as Ambiguous-period comparisons, and 79 Work-period conflicts (19 of them on strict pairs), the Name-space variant adds H (829/1072, Mario Collymore / Mariocollymore on 23 September), and ticket #11 adds 21 Flagged-duplicate counterparts (one uncertain, K 2188/2187) and 11 Repeated components (M 1575/2149 among them), for 85 possible duplicates in all. I's flagged row 318 has two counterparts, Approved 1545 and Rejected 999 (a strict pair with each other), so its possible duplicate holds all three. H stays apart from F (2206/2351, the same employee on 10 September): different dates, different display identifiers. A (591/593), L (2151/2152) and J against Orlando's row 137 are not linked, and "Compare two tickets" says why.

## Patterns and source states

At the top of Review priorities, a count matrix shows how the Candidates spread over the PRD's patterns and the tickets' source states, beside a pattern filter (side by side from 1200 px wide, stacked below).
Nothing in it is a partition, and its caption says the pattern counts overlap.

- **What a cell counts.** Distinct tickets inside the global filters, in that source state, that a Candidate of that pattern links (decision-log entry 64). Tickets listed only for comparison are not counted, so with Status Pending every Approved column is 0, as the tiles are.
- **Source states.** Each ticket has exactly one: Approved and Keyed, Approved and not Keyed, Pending, Rejected, or Flagged duplicate (Approved with Job Number 0, whatever its Keyed; the Approved columns leave flagged duplicates out). A sixth column, Status or Keyed unreadable, appears only when a ticket is in it (entry 65).
- **Rows.** Patterns 1-5, each with its tickets and the possible duplicates holding one of them, and an "Any pattern, each ticket once" row. A row's cells add up to its tickets, but the rows overlap: on the committed workbook they hold 207 tickets and 96 possible duplicates, against 186 (`candidate_ticket_count`) and 85 in the Any pattern row. Pattern 6, Service date in description, never links tickets and has no row.
- **Pattern filter.** Checkboxes, one per pattern with its own counts; several patterns list the possible duplicates matching any of them. The totals count distinct possible duplicates and distinct tickets once each and say so when the chosen patterns' own counts add up to more (entry 66). Choosing a matrix count (click, or Tab and Enter) selects its pattern and source state, so the list then holds exactly that many tickets; "Any source state" and "Clear pattern filter" undo it.
- **Every member stays listed.** A possible duplicate is listed when any member matches: inside the global filters, in a chosen source state and linked by a chosen pattern. Its other members are labelled "Outside the filters" or "Outside the pattern filter". A row whose tickets are in more than one source state adds a "Mixed source states" count line above them (entry 67).
- **Scope.** The pattern filter narrows only the ranked list; the matrix, the tiles and the other views ignore it.

## Evidence drawer

Selecting a possible duplicate opens a wide drawer (a modal dialog; Escape or Close returns to the list) so it can be investigated without opening Excel:

- **Why these tickets are together**: the reason in words, every Candidate with its rule, the two Excel rows, the fields compared, the evidence strength and how the two tickets' work periods compare (an overlap of Plausible Readings is labelled assumed), and the members' states ticket by ticket (status, Keyed, flagged duplicate), never a paid or unpaid summary.
- **Review outcome**: the reviewer label, a Confirm/Reject decision with a reason on each proposed Alias about the members' names, a Review Outcome with note and supporting reference for each Ticket pair, the kept and replaced tickets, and the review history; see [Review outcomes](#review-outcomes) and [Aliases](#aliases).
- **Annotations**: when a member's ticket number is one of the evidence report's 29 example Tickets, its example letter (A-N), title, pattern, the condensed review note, the questions for Oliver and the report section they come from (`docs/source/labour-ticket-report-readable.md`). A possible duplicate with no annotated ticket shows none.
- **Claim timeline**: the members in Created order with Date, Created, Approval Status, the four claim components (Regular Hours, Overtime, Double Time, Job Work Pay), Date Approved, Modified and Supervisor, so H's Pending ticket created before the Approved one and M's no-hours ticket created after the one with hours read down the table.
- **Source rows, side by side**: all source columns transposed, the field-name column fixed while the ticket columns scroll, each differing field highlighted and marked "Differs". A value differs when its text (exactly as written, spaces included), number, date, true/false or blank differs; 8 and 8.0 are the same number, but 0, false, blank and the text "0" are four different values. Cells render as text, never HTML, keeping line breaks and spaces; "Show whitespace" quotes text and draws spaces (·), tabs (→) and line breaks (↵) without changing the values.
- **Time as parsed**: each member's raw Time, parse status, each period's confidence, interval and Plausible Reading (labelled assumed), and the parser version.
- **Dates in the description**: for any ticket whose description names a date, each date as written, how it reads, whether it differs from Date (kept as recorded) and whether it is uncertain; see [Description-date exception](#description-date-exception).
- **Where each ticket comes from**: Excel row, dataframe index, sheet and workbook fingerprint, with any import issues.

**Compare two tickets**, below the ranked list, takes any two Excel rows and opens the same drawer on that pair, linked or not: "Why these tickets are (not) linked" gives every rule's verdict with its reason, how the work periods compare and which possible duplicate each ticket is in, then the Annotations, timeline, source rows, Time as parsed and provenance. For A (rows 591 and 593) it says the Confident Intervals 12:30-16:30 and 07:30-11:30 do not intersect, so these are separate work periods, and that equal hours on the same day never link tickets on their own.

## Flagged duplicates

Below the ranked list, **Flagged duplicates** lists every Ticket the Flagged duplicates tile counts (Approved with Job Number 0, which Oliver described as "more than likely a duplicate"), under the same filters, so the list always holds the tile's number.
Each says **Counterpart found** (with every counterpart's ticket, source state and pair outcome, uncertain ones marked) or **Unresolved** (no counterpart found), whether a reviewer settled it, and the possible duplicate it is in with that one's priority.
The split is shown here, beside the tile and never folded into its count; on the committed workbook it is 16 counterpart found and 12 unresolved.
A Show filter (All, Counterpart found, Unresolved) narrows the list. Each row opens the drawer: the possible duplicate holding the flagged ticket, addressed by that ticket, or, for a flagged duplicate no rule links, the ticket on its own with its timeline, source row, Time as parsed and provenance.

Annotations live in `src/labour_ticket_analytics/annotations.json`, extracted once from the evidence report and keyed by ticket number; the report's Excel row is kept for reference only.
They attach by ticket number, so they survive a re-export, and no matching rule reads them.
Each example carries its pattern's numbered questions for Oliver, since the report asks its questions per pattern; E and F have no review note in the report.
Notes are quoted verbatim except C and D, reworded (and marked `review_note_reworded`) so no screen shows "paid twice", "missed duplicate" or "fraud"; `source_section` names where the original wording stays.

## Processing queue

Two separate horizontal bar charts, **Pending submissions** and **Approved, not Keyed submissions**, count Tickets by **age since submission**: the as-of date minus the calendar date of Created, in whole days, from the registry metrics `pending_submission_age_days` and `approved_not_keyed_submission_age_days`.
It is never time spent Pending or waiting to be Keyed, which the export does not record; the caption names the date basis and the as-of date, and the view states its grain (Ticket) and the active filters.
On the committed workbook, as of 8 October 2026, they cover 129 and 149 Tickets:

| Age since submission | 0 days | 1 day | 2 days | 3 days | 4–6 days | 7–13 days | 14–29 days | 30 days or more |
|---|---|---|---|---|---|---|---|---|
| Pending | 19 | 40 | 34 | 18 | 13 | 2 | 2 | 1 |
| Approved, not Keyed | 21 | 20 | 22 | 40 | 46 | 0 | 0 | 0 |

The buckets belong to the registry (decision-log entry 57): fixed edges, both ends inclusive, so changing the as-of date moves Tickets between buckets, and a Ticket whose Created is unusable or after the as-of date is reported beside the chart rather than aged.
The global filters narrow both charts; a date range applies to its own date basis, while age is always measured from Created.

Clicking a bar, or opening **View data** (the table alternative under each chart) and choosing an age, lists that bucket's Tickets oldest first with Ticket Number, Excel row, employee, Date, Created and age; the list says it holds exactly the bar's count under the filters, as-of date, Snapshot and registry version shown. Each ticket opens on its own in the evidence drawer.

Charts are drawn by a small trusted-template module, `frontend/src/charts` (Vega-Lite, decision-log entry 59): the data is passed inline, nothing is loaded from a URL, no specification may carry an expression or transform, the value axis starts at zero, every bar is labelled directly, and every chart has its table alternative.

## Data readiness

Below the Processing queue, **Data readiness** answers which records cannot be reliably compared or valued with six compact counts under the global filters (decision-log entries 68-71).
Each is a button: choosing it (click, or Tab and Enter) lists exactly the rows it counts, under the same filters, window and Snapshot, and each listed ticket opens on its own in the evidence drawer.
The counts overlap and are never added together; nothing in them corrects a value.

| Count | What it holds | Metric | Committed workbook, all dates |
|---|---|---|---|
| Ambiguous times | Tickets whose Time parse result holds an Ambiguous Interval (a period without AM/PM), flagged results included | `ambiguous_interval_ticket_count` | 728 |
| Dates outside the reporting window | Tickets with a Date as recorded, Created or Date Approved outside the window; listed as recorded, never reassigned | `anomalous_date_count` | 3 (rows 756, 1265, 2502: the 2036 and 2050 work dates) |
| Date conflicts in descriptions | Tickets whose description names a date that differs from Date (the Description-date exception) | `description_date_conflict_count` | 33 (N's 1727 and 1728 among them) |
| Unresolved name proposals | Aliases the Name-space variant proposes with no saved decision, inside the filters when any proposing ticket is; each opens its possible duplicate to be confirmed or rejected, and drops out once decided | none: proposals, not tickets | 1 (H's Mario Collymore / Mariocollymore) |
| Missing rates | Tickets whose Rate is blank or not a number; the view states how many claim positive hours, whose labour is unpriced, never zero | `missing_rate_count` | 129, of which 122 claim 881 hours (all Pending) |
| Missing required fields | Tickets with a blank row, an empty required cell or a missing Ticket Number among their import issues | `missing_required_field_count` | 0 |

The **reporting window** is shown above the counts: two inclusive dates, by default 1 January of the earliest Created year to 31 December of the latest (all of 2026 on the committed workbook). Changing it and choosing Apply window recounts the out-of-window dates; "Use the Created years" restores the default. It is not saved.
A count whose column is missing (Rate, Description of Job Work) shows as not available, with the reason.

### Description-date exception

Each Ticket's Description of Job Work is read once at import for explicit dates and compared with Date; the result is versioned with the rules and never creates a Candidate, links two tickets or changes Date (PRD section 5, pattern 6).
Recognised: ISO dates (`2026-09-12`); a day with a month name in full or abbreviated, the year optional (`12 September`, `12th September 2026`, `9th of September`, `11 th September`, `4 Sep 26`, `Sept 12`, `September 12th, 2026`); slash dates (`12/09`, `12/09/2026`); and ranges joined by `to`, `till`, `until`, `through` or a dash, where an ordinal end may borrow the other end's month (`2nd to 8th Sep`, `Sep 2nd to the 10th`) and a year written on one end is the range's year.
Not dates: an ordinal day with no month (`the 10th`), dotted or coloned numbers (amounts and times), `7/30am`, `1/2 day`, and anything that is not a calendar date.
A date with no year is compared in Date's year and marked uncertain (`year_omitted`), a two-digit year is read as 20YY (`two_digit_year`), and when both slash numbers could be the month both readings are kept (`day_month_order`); the order is never chosen.
A Ticket is a date conflict when any of its dates differs from Date: a single date that is not Date, a range that does not contain it, or a slash date neither of whose readings is Date. The wording around a date is not interpreted, so a vacation ticket's return date counts too.
Without a Description of Job Work column the check is disabled and says so.

## Value context

Money is context, never the headline: the panel at the foot of the Overview is a disclosure, collapsed until opened (by click, or Tab and Enter on its heading).
It shows three figures in Barbados dollars (BBD), each a registry metric under the active filters, with its formula, interpretation and a completeness note computed from the metric's coverage (decision-log entries 60-63):

| Figure | Metric | On the committed workbook, all dates |
|---|---|---|
| Known base-value components | `known_base_value_bbd`: Rate × (Regular Hours + Overtime + Double Time) + Job Work Pay, rounded half-up to cents per ticket and then summed, over every ticket including Rejected | BBD 341,477.32 |
| Base value of flagged duplicates | `flagged_duplicate_base_value_bbd`: the same per-ticket value over the tickets `flagged_duplicate_count` counts | BBD 3,399.71 (28 tickets) |
| One extra claim per exact repeat, not flagged (hypothetical) | `unflagged_exact_repeat_extra_claim_bbd`: for each possible duplicate `unflagged_exact_repeat_count` counts, the n − 1 lower per-ticket values of its n tickets | BBD 571.37 (C, D, E and F: 4 exact repeats, 8 tickets) |

- **Unpriced labour is never zero.** Labour on a ticket with no usable Rate (or an hour cell that is not a number) is unpriced: the panel states it (881 hours across 122 Pending tickets on the committed workbook) and its value is in no figure, while the ticket's Job Work Pay still counts. No rate is substituted or taken from another person. An exact repeat with an unpriced ticket is left out of the hypothetical figure and reported.
- **Never added together.** The flagged and unflagged scenarios overlap and are separate questions; nothing sums them. The hypothetical n − 1 count applies to Strict repeat groups only, never to overlapping or partly matching tickets. A table under the figures lists each exact repeat with its tickets, Excel rows, per-ticket value, extra claims and the evidence report's example letter.
- **Analyst-reviewed alternative.** Only when a reviewer has linked a replaced ticket to a kept one does the panel add `reviewed_known_base_value_bbd`, labelled "Analyst-reviewed", beside the recorded figures: the known components without the replaced tickets (`replaced_tickets`), and how much they held. A Review Outcome, Needs follow-up or a note alone never changes any figure. Removing the last link withdraws it.
- **Wording.** No label or text on the panel says paid, saved, lost or liability; the export holds no payment records, so no figure is an amount disbursed, avoided or owed.

## Review outcomes

A reviewer records a local judgement from the evidence drawer without touching the source; nothing is written to the workbook or the company's system.

- **Reviewer label.** There are no accounts: the drawer asks for a reviewer label, remembers it in the browser, and records it with every save.
- **Review Outcome per Ticket pair.** Each pair of Tickets a Candidate links gets one of Not reviewed, Confirmed duplicate, Not a duplicate, Replacement ticket or Needs follow-up, with an optional note and supporting reference. The pair is order-independent and keyed by the Snapshot fingerprint and its two Excel rows, lower first; the ticket numbers are stored beside it for a later carry-forward, never as the key (`docs/adr/0004`, decision-log entry 33). A possible duplicate shows the outcome of each of its pairs and is never the key; the ranked list shows them too. The only thing an outcome or link moves is a tier: settling a flagged duplicate's counterpart pair moves its possible duplicate from tier 3 to tier 4 (see [Matching rules](#matching-rules)).
- **Kept and replaced tickets.** A replaced Ticket is linked to each Ticket kept in its place, and may have several; no single survivor is forced. Both Tickets must be in one possible duplicate, and a link that would close a loop, leaving no ticket kept, is refused; chains are allowed. Links are independent of the outcome (entry 34).
- **History.** Every save that changes an outcome, note or reference, and every link made or removed, appends a row with the reviewer label, the time (UTC), the previous value, the new value and the rationale. Changing a saved outcome, note or reference needs a rationale; saving what is already saved adds nothing (entry 35). The drawer lists the history of its tickets, newest first.
- **No numerical effect.** An outcome or a note changes no figure. Only an explicit kept/replaced link names a Ticket an adjusted figure may leave out (`replaced_tickets`); every existing metric and tile stays as recorded, and the value panel shows the adjusted figure only as a separately labelled analyst-reviewed alternative (see [Value context](#value-context)).
- **Wording.** A label, note, reference or rationale saying "paid twice", "missed duplicate" or "fraud" is refused, since no screen may show them (entry 36).
- **Storage.** One DuckDB file, `review.duckdb` in `--data-dir`, holds the review data (outcomes, links, Alias decisions and history) of every Snapshot keyed by its fingerprint, physically apart from the in-memory Snapshot tables (`docs/adr/0002`). A different workbook starts with no outcomes; the same workbook finds them again after a restart. A second running copy on the same data directory is refused at launch (entry 37). A review file written before Aliases existed (schema version 1) is upgraded in place on launch and keeps everything it holds (entry 51).

## Aliases

The Name-space variant proposes that two employee labels name one person, such as "Mario Collymore" and "Mariocollymore" (H); a reviewer confirms or rejects the proposal from the evidence drawer.

- **Keyed by the label pair.** A decision is stored per Snapshot fingerprint and unordered pair of normalized labels, and only for a pair some Name-space variant proposes (entry 49). Proposed means nobody has decided; a reviewer saves Confirmed or Rejected, always with a reason, and each change is a history row with the reviewer label, time, previous and new decision and the reason. Saving the decision already saved changes nothing.
- **What a confirmed Alias does.** The rules run again over the whole Snapshot as soon as a decision changes, and at every launch under the Aliases already confirmed, so the Work-period conflict compares both labels' Tickets as one employee on every date (entry 50). The response lists the Candidates the run added and removed. Rejecting removes what confirming added; the Name-space variant Candidate itself stays.
- **What it never does.** It never merges labels: members keep their own names, the Strict repeat, Time-text variant and Ambiguous-period comparison still compare one label (so H is never an exact repeat), and `employee_label_count` counts both labels. An Alias joins only its own two labels, never transitively. A shared email is never a reason: Peter Holder and Renaldo Springer share one on the same claim (rows 171/173) and are not proposed.
- **Review data survives a rerun.** Outcomes and links are keyed by Ticket pairs and rows, never by Candidates, so a rerun deletes nothing; an outcome on a pair that loses its last Candidate stays saved and shows again if a later decision links the pair.

## API

| Request | Returns |
|---|---|
| `GET /api/snapshot` | the active Snapshot header (fingerprint, sheet, row and field counts, fields, import issues, missing optional columns, disabled features) plus the as-of date in effect and the application version |
| `POST /api/snapshot/reimport` | reads the workbook at the launch path again. Identical content keeps the same Snapshot (`"imported": false`); different content becomes a new active Snapshot beside the old one (`"imported": true`). A workbook that cannot be imported answers 422 and the active Snapshot stays. Requests from another site's page are refused |
| `GET /api/snapshots` | every Snapshot imported in this run, oldest first, with the active one marked |
| `GET /api/as-of`, `PUT /api/as-of` | the analytical as-of date in effect; `PUT {"date": "YYYY-MM-DD"}` changes it for every later response. It stays labelled as an assumption and never follows today's date. Requests from another site's page are refused |
| `GET /api/metrics` | the metric registry and its version: the thirteen PRD metrics, the value panel's `flagged_duplicate_base_value_bbd`, `unflagged_exact_repeat_extra_claim_bbd` and `reviewed_known_base_value_bbd`, and the data readiness counts `ambiguous_interval_ticket_count`, `anomalous_date_count`, `description_date_conflict_count`, `missing_rate_count` and `missing_required_field_count`, each with ID, label, definition, unit, grain, allowed dimensions, null treatment, date basis, exclusions, lineage, `buckets` (the value ranges a distribution is counted by: `id`, `label`, inclusive `min` and `max`, `max` null when open-ended; empty for other metrics), `reads_review_links` (true only for the analyst-reviewed figure, which leaves out the replaced tickets), `reads_reporting_window` (true for `anomalous_date_count`) and availability (`available`, or `disabled` by a missing column) |
| `GET /api/metrics/{metric_id}` | one metric under the filters below: its value (a count, sum, or for day and hour metrics the median with a `summary`; `unflagged_exact_repeat_count` counts possible duplicates and gives their `tickets`; `unflagged_exact_repeat_extra_claim_bbd` also gives its `possible_duplicates` with their values), `percentage` with numerator and denominator where the metric is a share of `ticket_count`, `coverage` naming the Tickets left out or only partly valued and why, and `warnings`. `group_by` takes an allowed dimension (`Approval Status`, `Keyed`, `Job Number`, `Job Name`, `Supervisor`, `Occupation`); `rows=true` lists the contributing Excel rows. A metric with buckets also gives `buckets`, each with its `tickets` count, an empty bucket as 0. A metric that reads the reporting window takes `window_from` and `window_to` (inclusive ISO dates, each defaulting to the years Created covers) and gives the `reporting_window` it used |
| `GET /api/metrics/{metric_id}/buckets/{bucket_id}` | the Tickets one bucket counts, under the filters and as-of date: `metric`, `bucket`, `tickets` (the count) and `rows`, highest value first then earliest Created, each with `excel_row`, `ticket_number`, `employee`, `date`, `created`, `status`, `keyed` and `value` (for the age metrics, days since submission), plus the filter state. 404 with `detail.code` `unknown_metric`, `no_buckets` or `unknown_bucket` |
| `GET /api/overview/processing-queue` | the Processing queue under the filters: two `charts` (`pending_submission_age_days`, `approved_not_keyed_submission_age_days`), each with `title`, `population`, `caption` ("Age since submission"), `measured_on`, `chart` (`bar_horizontal`), `total`, `summary`, `buckets` with counts, `coverage` and `warnings`; plus the `note`, the grain and the filter state |
| `GET /api/overview/value-context` | the value-context panel under the filters: `title`, `currency` (`BBD`), `note`, three `figures` (each with `metric_id`, `label`, `scenario` (`recorded`, `flagged` or `hypothetical`), `value`, `formula`, `interpretation`, `completeness`, `definition`, `tickets`, `coverage` and `warnings`; the hypothetical one adds `possible_duplicates`, each with `excel_rows`, `ticket_numbers`, `employee`, `tickets`, `extra_claims`, `ticket_values`, `value` and `examples`), `unpriced_labour` (`tickets`, `hours`, `statuses`, `excel_rows`, `summary`), and `reviewed_alternative`: null unless a kept/replaced link exists, otherwise the analyst-reviewed figure with `replaced_tickets`, `replaced_in_filter` and `left_out_value` |
| `GET /api/overview/data-readiness` | the Data readiness view under the filters and `window_from`/`window_to`: `title`, `question`, `note`, six `checks` (each with `id`, `label`, `metric_id` (null for `unresolved_identity`), `unit`, `grain`, `description`, `count` (null when a missing column disables it), `definition`, `availability`, `summary` and `warnings`), the `reporting_window` (`from`, `to`, `default_from`, `default_to`, `is_default`, `dates_checked`, `description`, `note`) and the filter state. A window ending before it starts answers 422 (`detail.field` `reporting_window`) |
| `GET /api/overview/data-readiness/{check_id}` | exactly the rows one count counts, by Excel row, under the same filters and window: `check`, `count` and `rows`. A ticket row has `excel_row`, `ticket_number`, `employee`, `date`, `created`, `status`, `keyed`, `in_filter` and a `detail` for its check (the ambiguous periods; the dates outside the window, as recorded; the `description_dates`; the Rate cell, claimed hours and `positive_hours`; or the import issues); an `unresolved_identity` row has the `labels`, `names`, `decision`, `proposed_by` pairs with ticket numbers, and the `possible_duplicate` holding its first proposing ticket (`excel_row`). 404 with `detail.code` `unknown_check` |
| `GET /api/overview/tiles` | the five header tiles under the filters, with their definitions, the overlap note, the grain and the filter state; a tile counting possible duplicates also gives their `tickets` |
| `GET /api/review-priorities` | the ranked possible duplicates under the filters and the pattern filter: each with `rank`, `display_id`, `tier`, `rule_ids`, `pattern_labels`, `pattern_ids`, `source_states` (members per source state), `summary`, its `members` (Excel row, ticket number, employee, Date, Job Number, status, Keyed, `flagged_duplicate`, Created, `in_filter`, `source_state`, `in_selection`) and its `candidates` (Excel rows, rule ID, fields compared, evidence strength, reason, pattern, and the pair's Review Outcome as `outcome`, display only); plus the tier and rule definitions, `pattern_filter` (the chosen `patterns` and `source_states`, `active`, `description`, `counts` per pattern, union `totals` of `possible_duplicates` and `tickets`, and a `note`) and `pattern_matrix` (`caption`, `note`, `grain`, `source_states`, `rows` per pattern with `possible_duplicates`, `tickets` and `cells`, and `any_pattern`). Repeatable `pattern` (`same_claim_twice`, `same_claim_as_different_text`, `correction_or_resubmission`, `equal_duration_separate_periods`, `repeated_payment_component`) and `source_state` (`approved_keyed`, `approved_not_keyed`, `pending`, `rejected`, `flagged_duplicate`, `unreadable`) narrow the list; anything else answers 422. A filter selects a possible duplicate when any member matches it, and every member stays listed |
| `GET /api/filters` | what the filter bar offers: date bases with their date spans, statuses and jobs with Ticket counts |
| `GET /api/snapshots/{fingerprint}/tickets/{excel_row}` | one Ticket: its Excel row, dataframe index (Excel row minus 2), sheet, its import issues, and all cells with field name, position, raw type, raw value and number format. Blank cells have raw type `blank` and a null value; a numeric zero stays `0`; booleans stay `true` or `false`; dates are ISO 8601 text with raw type `datetime`; formulas have raw type `formula` and their formula text |
| `GET /api/snapshots/{fingerprint}/tickets/{excel_row}/possible-duplicate` | the evidence for the possible duplicate holding that Ticket; any member's row gives the same answer, and the display name is never the address. `display_id`, `tier`, `pattern_labels`, `reason`, `candidates` (each with `rule_label`, `time_comparison` and its pair's `outcome`), `review` (the five `outcome_values`; `pairs`, one per Candidate pair with its outcome, note, reference, reviewer, `recorded_at` and `saved`; `aliases`, each Alias about two members' labels with its decision and history, and the `alias_decision_values`; the `links` and `history` touching its members or those Aliases), `status_breakdown` (member states, never payment), `members` (with `employee_label`, `provenance`, `issues`, `time_parse` and `description_dates`: the check's `status` (`conflict`, `agrees`, `no_date_reference`, `blank`, `not_text`, `date_unusable` or `disabled`), `conflict`, `uncertain`, `date`, `rule_version`, `note` and `references`, each with `text`, `start`/`end` offsets in the description, `kind` (`date` or `range`), `interpretation`, `readings` (inclusive `from`/`to` spans), `year_written`, `uncertain`, `uncertainty`, `notes` and `differs_from_date`), `timeline` (members by Created with Date, Created, Approval Status, the four claim components, Date Approved, Modified, Supervisor), `fields` (one row per source column with `differs` and each member's raw type and value), `differing_fields` and `annotations`. Takes the filter parameters to label out-of-filter members. 404 when the Ticket is in no possible duplicate |
| `GET /api/snapshots/{fingerprint}/tickets/{excel_row}/evidence` | one Ticket's evidence on its own: `excel_row`, `possible_duplicate` (the display name of the one holding it, or null), and the drawer's `members`, `timeline`, `fields`, `differing_fields` and `annotations`. Takes the filter parameters. 404 for an unknown row or Snapshot |
| `GET /api/flagged-duplicates` | every flagged duplicate inside the filters (the Tickets `flagged_duplicate_count` counts), lowest ticket number first, each with its member fields, `counterpart_status` (`counterpart_found` or `unresolved`), `counterparts` (each counterpart Ticket's member fields, the pair's `excel_rows`, `certain`, `reason`, `settles` and `outcome`), `settled_by_review`, and `possible_duplicate` (`display_id` and `tier`, or null); plus `counts` (`flagged_duplicates`, `counterpart_found`, `unresolved`), the `counterpart_statuses` with definitions, `metric_id`, a `note` and the filter state |
| `GET /api/snapshots/{fingerprint}/pairs/{row}/{row}` | why two Tickets are or are not linked, in either row order: `excel_rows` (lower first), `same_employee_and_date` (inside the search space), `employee_relation` (`same_label`, `confirmed_alias`, `spacing_differs`, `different` or `unusable`), `linked`, `rules` (every rule's `rule_id`, `rule_label`, `matched`, `evidence_strength`, `fields_compared` and `reason`, matched or not), `summary`, `time_comparison`, `possible_duplicate` (holding both, or null), and the drawer's `members` (each with its `possible_duplicate`), `timeline`, `fields`, `differing_fields` and `annotations`. Takes the filter parameters. 422 for one row given twice, 404 for an unknown row or Snapshot |
| `GET /api/snapshots/{fingerprint}/review` | everything saved for a Snapshot: `outcome_values`, saved `outcomes`, saved Alias decisions as `aliases`, `links`, `replaced_tickets` (the only Tickets an adjusted figure may leave out), `history` (newest first) and the review file in `store` |
| `GET /api/snapshots/{fingerprint}/pairs/{row}/{row}/outcome`, `PUT` the same | a Candidate pair's Review Outcome (Not reviewed until saved) with its `history`; either row order is the same pair. `PUT {"outcome", "note", "reference", "reviewer", "rationale"}` saves it and answers with `changed`. `outcome` is `not_reviewed`, `confirmed_duplicate`, `not_a_duplicate`, `replacement_ticket` or `needs_follow_up`. 404 (`no_candidate`) when no Candidate links the rows; 422 with `detail.code` for an unknown outcome, a blank reviewer, text over its limit, a banned phrase, or a revision without a rationale. Requests from another site's page are refused |
| `PUT /api/snapshots/{fingerprint}/replacement-links/{replaced_row}/{retained_row}`, `DELETE` the same | links a replaced Ticket to a kept one, or removes the link, with `{"reviewer", "rationale"}`; each change is a history row. 422 unless both are in one possible duplicate, 409 (`link_loop`) when the kept ticket already leads back to the replaced one through existing links, 404 when removing a link that does not exist. Requests from another site's page are refused |
| `GET /api/snapshots/{fingerprint}/aliases` | every Alias the Name-space variant proposes: `labels` (normalized, sorted), `names` as written, `proposed_by` (the Ticket pairs), `decision` (Proposed until saved), `reviewer`, `recorded_at`, `rationale`, `saved` and its `history`; plus the `decision_values` and a `note` |
| `PUT /api/snapshots/{fingerprint}/aliases` | `{"labels": [two names, as written or normalized], "decision": "confirmed" or "rejected", "reviewer", "rationale"}` saves a decision and, when it changed, runs every rule again: answers with the Alias, `changed`, `rules_ran` and `rerun` (`added` and `removed` Candidates, each with `rule_label`). 404 (`no_alias_proposal`) for a pair no Name-space variant proposes; 422 with `detail.code` for two labels that are one, an unknown decision, a missing reason, a blank reviewer or a banned phrase. Requests from another site's page are refused |
| `GET /api/annotations` | the evidence report's 14 examples (A-N) with title, pattern, summary, `review_note` (null where the report has none; `review_note_reworded` marks C and D), `source_section`, `questions_for_oliver` and their 29 ticket numbers, each with its Excel row in the active Snapshot |
| `GET /api/snapshots/{fingerprint}/tickets/{excel_row}/time` | the Ticket's Time cell as parsed: raw type and value, parser version, status, each period with its text, confidence (`confident` or `ambiguous`), interval, Plausible Reading (`assumed: true`), flags and notes, the union of its Confident Intervals, and notes on the status |
| `GET /api/snapshots/{fingerprint}/time-parses` | how every Time cell in the Snapshot parsed: Ticket counts and Excel rows by status and raw type |
| `GET /api/snapshots/{fingerprint}/time-comparison?excel_row=A&excel_row=B` | whether two Tickets' work periods overlap: `result`, `basis`, `assumed`, the `intersection` and `overlap_minutes`, an explanation, and both parse results. Exactly two rows, or 422 |

Filters are query parameters on the metric and tile requests: `date_basis` (`Created`, `Date` or `Date Approved`, default `Created`), `date_from` and `date_to` (inclusive ISO dates on that basis), and repeatable `job` and `status`; Review priorities also takes the repeatable `pattern` and `source_state`.
Without a date range every metric covers all dates, so totals reconcile with the import; a Ticket whose filtered value is unusable falls outside an active filter.
A filter, metric or dimension outside the allowlist answers 422 (404 for an unknown metric) with `detail.code`, `detail.field` and `detail.message`.

Every response that carries numbers also carries `snapshot_fingerprint`, `as_of` and `versions` (`app`, `registry`, `rules`, `parser`).

## Tests

The one test seam is the HTTP API of the booted application, run against the committed workbook (`docs/adr/0003`).
A refused launch never reaches HTTP, so those tests assert on the launch command's exit status and error message instead.
The fixture in `tests/conftest.py` starts the real process on an ephemeral loopback port with a temporary data directory; review tests boot twice on one data directory to prove outcomes persist.
Tests that need shapes the export does not have build a minimal same-schema workbook at test time with `tests/synthetic.py`.

```sh
uv run pytest                             # API tests
npm --prefix frontend run typecheck       # TypeScript, app and frontend/e2e
npm --prefix frontend run build           # then the browser tests, which need the built frontend
npm --prefix frontend run e2e             # Playwright flows in frontend/e2e against the running process
```

One test is skipped until the frontend has been built.
The browser tests (`@playwright/test` 1.56.1, Chromium) boot the application themselves on an ephemeral port with `.venv/bin/python` (override with `LTA_PYTHON`), and build any synthetic workbook through `tests/synthetic.py`; they assert text, roles and keyboard focus, not pixels.
Install the browser once with `npx --prefix frontend playwright install chromium`.
CI (`.github/workflows/ci.yml`) builds the frontend and runs all three on every pull request and on `main`.

## Layout

```
src/labour_ticket_analytics/   cli (launch), workbook (import), schema (columns), validation (import issues), normalized (Ticket values for metrics),
                               metrics (registry), filters (filter bar), timeparse (interval parser), rules (matching rules, possible duplicates, priority),
                               evidence (evidence drawer payload), description_dates (Description-date exception), data_readiness (Data readiness view), pattern_matrix (pattern matrix and pattern filter), flagged (Flagged duplicates view), processing_queue (Processing queue view), value_context (Value context panel), annotations (+ annotations.json, the evidence report's notes),
                               versions, store (DuckDB Snapshot tables), review (local review file: outcomes, links, history), api (HTTP)
frontend/                      React + TypeScript shell built with Vite into frontend/dist (src: App, FilterBar, HeaderTiles, ReviewPriorities, PatternMatrix,
                               FlaggedDuplicates, ProcessingQueue, DataReadiness, ValueContext, CompareTickets, EvidenceDrawer, ReviewPanel; charts/ holds the trusted
                               Vega-Lite templates and their renderer); e2e/ holds the Playwright flows
tests/                         API tests at the booted-app seam
data/                          the committed source workbook (private repository, ADR 0003)
docs/                          PRD, decision log, ADRs, handoff sources
```
