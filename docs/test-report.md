# Release-one test report

Release one of Labour Ticket Analytics, tested on 15 October 2026 against the committed workbook (Snapshot `36378ee04717`, 2,836 rows, 22 fields).
This report closes ticket #18: it maps every PRD section 12 criterion to named tests, records the usability, accessibility and layout checks, and gives measured timings and the limitations that remain.

## Result

| Suite | Command | Result |
|---|---|---|
| API tests | `uv run pytest` | 352 passed |
| Typecheck and build | `npm --prefix frontend run build` | passed |
| Browser tests | `npm --prefix frontend run e2e` | 46 passed |
| Service logs, API run | checked at the end of `uv run pytest` | no employee names, emails or descriptions in 258 lines |
| Service logs, browser run | checked at the end of `npm --prefix frontend run e2e` | no employee names, emails or descriptions in 39 lines |

CI (`.github/workflows/ci.yml`) runs all three suites, and both log checks, on every pull request.

**One acceptance item needs a person.** The screenshots under `docs/screenshots` are committed; ticket #18 asks that a person review them. See [Layout and screenshots](#layout-and-screenshots).

### Environment

| Item | Version |
|---|---|
| Operating system | Linux 6.18 x86_64, 4 CPUs, 15 GB memory (a Claude Code cloud container) |
| Python | 3.13.16, packages pinned in `uv.lock` |
| uv | 0.11.32 |
| Node.js | 22.22.0, packages pinned in `frontend/package-lock.json` |
| Browser | Chromium 1194 via `@playwright/test` 1.56.1 |
| Accessibility engine | axe-core 4.13.0 via `@axe-core/playwright` 4.13.0 |
| Service versions | app 0.1.0, registry 1.6.0, rules 1.4.0, parser 1.0.0 |


## Section 12 data-correctness criteria

Each criterion of PRD section 12 maps to the named tests below, all at the HTTP API seam against the committed workbook.
`tests/test_acceptance_criteria.py` checks that every test named here exists, so the table cannot drift from the suite.

| # | Criterion | Tests |
|---|---|---|
| 1 | 2,836 rows, 22 fields, status and Keyed counts, 28 flagged duplicates, all computed | `test_snapshot_header.py::test_header_reports_row_and_field_counts_from_the_import`<br>`test_header_tiles.py::test_tiles_reproduce_the_published_counts_on_all_data`<br>`test_header_tiles.py::test_status_breakdown_and_keyed_split_are_available_through_the_registry`<br>`test_flagged_duplicates.py::test_the_flagged_duplicates_tile_shows_28_with_olivers_qualification` |
| 2 | The 34 strict two-record groups and C-F first, with reasons and member states | `test_review_priorities.py::test_the_strict_repeat_rule_finds_34_two_ticket_groups_with_the_published_source_states`<br>`test_review_priorities.py::test_the_four_unflagged_approved_keyed_exact_repeats_lead_the_list_oldest_created_first`<br>`test_review_priorities.py::test_every_candidate_carries_its_rule_fields_compared_evidence_strength_and_reason`<br>`test_review_priorities.py::test_each_row_shows_pattern_labels_an_evidence_summary_and_member_source_states` |
| 3 | All 638 source cells of the 14 comparisons, F apart from H, G's whitespace | `test_acceptance_source_cells.py::test_all_638_cells_are_checked_and_every_linked_example_opens_through_the_detail_api`<br>`test_acceptance_source_cells.py::test_every_source_cell_of_the_comparison_is_returned_exactly_as_the_report_prints_it`<br>`test_acceptance_source_cells.py::test_f_and_h_are_separate_possible_duplicates_though_both_are_mario_collymore`<br>`test_acceptance_source_cells.py::test_gs_whitespace_difference_in_time_survives_verbatim` |
| 4 | A separate, B's absent AM/PM surfaced, L's union with no false overlap | `test_time_rules.py::test_a_is_explained_as_separate_work_with_no_candidate`<br>`test_time_rules.py::test_b_is_an_ambiguous_period_comparison_whose_assumed_readings_do_not_overlap`<br>`test_time_rules.py::test_l_has_no_work_period_conflict_across_the_middle_gap` |
| 5 | J's assumed afternoon overlap shown, never asserted; row 137 kept apart | `test_time_rules.py::test_j_is_an_ambiguous_period_comparison_showing_the_assumed_afternoon_overlap_without_asserting_it`<br>`test_time_rules.py::test_orlandos_morning_hr_ticket_at_row_137_is_not_in_js_possible_duplicate` |
| 6 | H's Pending ticket created first; M's no-hours ticket created later | `test_flagged_duplicates.py::test_hs_drawer_shows_the_pending_ticket_was_created_before_the_approved_one`<br>`test_flagged_duplicates.py::test_m_is_a_low_confidence_repeated_component_and_the_no_hours_ticket_was_created_later` |
| 7 | I with Rejected row 999; N's description dates kept and no link on Date alone; K an uncertain counterpart | `test_flagged_duplicates.py::test_i_holds_rejected_row_999_as_context_with_318_and_1545_and_shows_the_chronology`<br>`test_description_dates.py::test_n_row_1727_carries_its_description_date_span_and_keeps_its_recorded_date`<br>`test_description_dates.py::test_n_row_1728_names_the_7th_without_a_year_so_its_reading_is_flagged_uncertain`<br>`test_description_dates.py::test_the_exception_creates_no_candidate_for_n`<br>`test_flagged_duplicates.py::test_k_is_an_uncertain_counterpart_through_identical_unresolved_time_text_and_description` |
| 8 | One interval overlapping two separate ones; no ticket called redundant | `test_time_rules.py::test_a_three_ticket_possible_duplicate_shows_both_overlap_edges_and_calls_no_ticket_redundant` |
| 9 | BBD 341,477.32, 3,399.71 and 571.37, missing-rate coverage, never called payments | `test_value_context.py::test_the_panel_reconciles_the_three_published_figures_from_the_registry`<br>`test_value_context.py::test_the_known_components_disclose_881_unpriced_hours_on_122_pending_tickets`<br>`test_value_context.py::test_no_label_says_paid_saved_lost_or_liability_and_the_figures_are_never_added_together` |
| 10 | Every chart's drilldown reproduces its total under the same filters, Snapshot and versions | `test_acceptance_drilldowns.py::test_every_header_tile_drills_down_to_exactly_the_tickets_it_counts`<br>`test_acceptance_drilldowns.py::test_the_flagged_duplicates_list_holds_exactly_the_tickets_the_tile_counts`<br>`test_acceptance_drilldowns.py::test_every_pattern_matrix_cell_drills_down_to_a_list_whose_ticket_total_is_the_cell`<br>`test_acceptance_drilldowns.py::test_every_processing_queue_bucket_drills_down_to_its_count_and_the_buckets_sum_to_the_chart`<br>`test_acceptance_drilldowns.py::test_every_data_readiness_count_drills_down_to_exactly_its_rows`<br>`test_acceptance_drilldowns.py::test_every_value_figure_drills_down_to_the_tickets_it_values`<br>`test_acceptance_drilldowns.py::test_every_starter_plan_drills_down_to_its_chart_total_and_every_bar_under_the_inherited_filters` |

## Usability flows

Each task runs in the browser against the committed workbook, without SQL or Excel, and reaches every control by keyboard.

| Task | Test | What it proves |
|---|---|---|
| Investigate C | `evidence-drawer.spec.ts`: "the Peter Holder possible duplicate opens from the list by keyboard and its drawer reads end to end" | C opens by Tab and Enter; the drawer shows the reason, member states, annotation C with the questions for Oliver, the Created timeline, all 22 source fields with the five that differ marked, provenance and the time parse; Escape returns focus |
| Compare F with H | `acceptance.spec.ts`: "the second usability task: F and H open by keyboard as separate possible duplicates on different dates" | F (10 September) and H (23 September) open as different possible duplicates with no shared ticket; comparing rows 2206 and 829 says they were never compared because the dates differ |
| Build, then refine, pending by supervisor | `explore.spec.ts`: "the third usability task: pending-by-supervisor bars built from the chips, then regrouped, by keyboard" | the chips build horizontal bars of 129 Pending tickets by supervisor with Other; the table alternative opens by keyboard; regrouping by occupation keeps the filter |

## Accessibility

`acceptance.spec.ts` checks, on every run:

- **Automated WCAG 2.1 AA audit.** axe-core finds no violations on the Overview, C's drawer, J's drawer (an uncertain time) and Explore with its table and source rows open.
- **Visible focus.** Each of the first 80 Tab stops on the Overview and 40 in the drawer shows an outline or ring.
- **Table alternatives.** Every Overview chart sits beside a "View data" table; Explore charts offer "View data" and "Inspect source rows".
- **Chart contrast.** Every opaque chart mark reaches at least 3:1 against the chart panel.
- **No green, and colour never alone.** No rendered colour on the Overview is green, so nothing suggests a verified payment; every coloured tag carries words.

The audit found five defects, all fixed in this ticket:

| Defect | Fix |
|---|---|
| The Overview and Explore tabs had no tab list around them | the tabs sit in a labelled `tablist` |
| The page had no level-one heading | the masthead title is the `h1` |
| Amber text for unresolved evidence reached only 4.0:1 | the amber darkens from `#b4690e` to `#9a5a0b`, 5.2:1 on the page and 4.9:1 on its own wash |
| Date inputs showed no focus ring, because focus sits on their inner day, month and year fields | a date input draws the focus ring whenever focus is inside it |
| The drawer's timeline and source tables scrolled but could not be reached by keyboard | both are labelled, focusable scroll regions |

## Explanatory states

Each state is reached in `acceptance.spec.ts` and says what to do next.

| State | How the test reaches it | Next action shown |
|---|---|---|
| Loading | holds the header request | "If it has not appeared within a few seconds, check the terminal where the service is running." |
| Empty | Explore range set to a month with no tickets | "Remove a filter or widen the date range." No chart and no zeros are drawn |
| Invalid import | the workbook is replaced with an unreadable file, then Reimport | "Correct the workbook at the path the service was launched with, then choose Reimport again." The current Snapshot stays active |
| Stale Snapshot | the workbook changes, then Reimport | "Its numbers are withdrawn until you run the plan again", with a Rerun the plan button |
| Uncertain parse | J's drawer, whose times lack AM/PM | "Next step: confirm the start and finish times with the employee or supervisor before treating these tickets as overlapping or as separate work." |
| Failed query | the plan request fails | "Change a chip to try again, or reload the page." |

The loading, invalid-import and uncertain-parse wording gained its next action in this ticket.
A launch that cannot import the workbook stops before the page exists; `tests/test_import_refusal.py` checks its message.

## Layout and screenshots

`layout.spec.ts` checks at 1440 and 1024 CSS pixels that the Overview, the evidence drawer and Explore never scroll sideways, that nothing outside a table's scroll box passes the right edge, and that the source comparison scrolls inside its own box.
At 1024 px a long metric identifier in the Value context first pushed past the edge; identifiers in code text now wrap.

Screenshots, written by `LTA_SCREENSHOTS=1 npm --prefix frontend run e2e -- layout`:

| View | 1440 px | 1024 px |
|---|---|---|
| Overview | `screenshots/overview-1440.png` | `screenshots/overview-1024.png` |
| Explore with chips and chart | `screenshots/explore-1440.png` | `screenshots/explore-1024.png` |
| C's expanded source comparison | `screenshots/source-comparison-1440.png` | `screenshots/source-comparison-1024.png` |
| Claimed hours by job, with its table (release 1.1) | `screenshots/claimed-hours-1440.png` | `screenshots/claimed-hours-1024.png` |

They show employee records from the committed workbook and stay in this private repository (ADR 0003).
**Person review:** pending.

## Release 1.1

Release 1.1 adds Overview panels on top of release one; each joins the acceptance checks above.

| Panel | Tests |
|---|---|
| Claimed hours by job (#33) | `tests/test_claimed_hours_panel.py` (scope, measures, filters, drilldowns, the reviewed alternative); `test_acceptance_drilldowns.py::test_claimed_hours_by_job_drills_down_to_every_bar_and_its_total` under the four filter states and both measures; `frontend/e2e/claimed-hours.spec.ts`; the accessibility audit, chart checks and layout checks now wait for the panel |

## Logs

The service logs only warnings and never logs requests.
Its start-up lines carry counts, the Snapshot identifier and file paths.
An unexpected exception keeps its type and code location in the log, but its message is withheld because it could quote a cell value (`logredact.py`, tested in `tests/test_log_redaction.py`).
Every service process both suites start has its output saved under `test-logs/`, and each run ends by checking it against 823 values from the workbook: every employee, supervisor and modifier name, every email and every description of 15 characters or more.

## Timings

Measured on the environment above, by `tests/test_acceptance_timings.py` and the "measured" test in `acceptance.spec.ts`.
They are recorded, not asserted.

| Measure | Result | Target |
|---|---|---|
| First load: launch to listening, import and rules included | 2.35 s | |
| First load: the Overview's seven first requests | 0.57 s | |
| **First load, total at the API** | **2.92 s** | under 10 s |
| First load in the browser: page open to a usable Overview | 0.62 s | |

Ordinary responses at the API, over five requests each:

| Request | Median | Slowest |
|---|---|---|
| Tiles, status filter | 0.108 s | 0.123 s |
| Tiles, job filter | 0.104 s | 0.112 s |
| Tiles, Created range | 0.104 s | 0.112 s |
| Review priorities, status filter | 0.023 s | 0.026 s |
| Pattern-matrix cell drilldown | 0.025 s | 0.085 s |
| Processing-queue bucket drilldown | 0.052 s | 0.056 s |
| Data-readiness drilldown | 0.287 s | 0.318 s |
| Evidence drawer for C | 0.084 s | 0.096 s |
| Explore plan execute | 0.048 s | 0.064 s |
| Explore bar drilldown | 0.056 s | 0.085 s |

In the browser: a Status filter change took 0.27 s to apply, opening C's drawer 0.27 s, and the first Explore chart 0.18 s.
Every ordinary response is under the 1-second target.

## Packaging

- **Launch.** `uv run labour-ticket-analytics "data/Labour Tickets Export.xlsx"` after the one-time setup in the README; one process serves the API and the built frontend on loopback.
- **Pinned dependencies.** Python 3.13 with `uv.lock`; Node 22 with `frontend/package-lock.json`; every frontend package at an exact version.
- **Metric and rule documentation.** `docs/metrics-and-rules.md`, generated from the running service and checked against it on every run, beside the README's rule and view sections.

## Unresolved limitations

- **Screenshots await a person's review**, as above.
- **Timings come from a cloud container, not your machine.** The PRD's reference machine is the consultant's own; run `uv run pytest -s tests/test_acceptance_timings.py` there to record its numbers.
- **Accessibility is automated, not a full audit.** axe-core covers part of WCAG 2.1 AA; no screen-reader session was run. The focus check covers the first 80 stops on the Overview and 40 in the drawer, and the no-green and contrast checks scan the Overview only.
- **The log check matches known values.** It looks for names of 5 or more characters with a space (or 10 run together), all emails and descriptions of 15 or more characters, so a short description could pass unnoticed. Browser console output and the output of launches refused before listening are not collected; refusal messages name only the file, sheet and columns.
- **Deferred to release two, as planned:** natural-language questions, the 390 px layout, the 50,000-row performance fixture, request cancellation and timeout, saved views, and carrying review decisions to a new Snapshot.
- **The export holds no payment records**, so no test can show that anything was paid, stopped or paid twice; the product never claims it.

