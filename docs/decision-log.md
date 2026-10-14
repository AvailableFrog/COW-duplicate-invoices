# Decision log

Changes from PRD v1.0 (`docs/source/labour-ticket-analytics-prd-v1.0.md`) to v1.1 (`docs/prd.md`), made in the design review of 14 October 2026.
Every PRD figure was independently recomputed from the workbook before the review and reconciled exactly; no change below corrects a number.
"Review" means the grilling session; R1/R2/R3 are its rounds.

| # | Change | Reason | Source |
|---|---|---|---|
| 1 | PRD revised in place as v1.1 rather than rewritten or accepted as-is | The analysis and evidence controls are correct; the problems were scope and cost | R1 Q1 |
| 2 | First user is the consultant on their own machine; the Oliver meeting (unscheduled) is the deadline | Fixes who release one serves and why it must be small | R1 Q2, R1 Q6, R3 Q1, R3 Q2 |
| 3 | Natural-language input moved to release two; release one Explore tab is deterministic plan controls | The stated success test is served without a model; the model layer is the most expensive and least needed half | R1 Q3, ADR 0001 |
| 4 | No inference spend in any release; release-two provider is a local open-weights model | The project is a prototype and the engagement forbids sending data to unapproved services | R1 Q4, R2 Q2, ADR 0001 |
| 5 | Stack kept (Python, DuckDB, React/TypeScript, Vega-Lite) but packaged as one loopback process with a single launch command | One user, one machine; a reviewer should not run a second dev server | R1 Q5, ADR 0002 |
| 6 | Workbook and handoff docs committed to this private repository | Cloud sessions start from a fresh clone; real-row tests must run there | R1 Q7, R3 Q1, ADR 0003 |
| 7 | Local Review Outcomes, Aliases and history stored in one local DuckDB file, physically separate from source tables | Keeps source state and local judgement apart, as the PRD requires | R1 Q8, ADR 0002 |
| 8 | Canonical vocabulary fixed; bare "duplicate" banned | The word was carrying five meanings in the source material | R1 Q9, `GLOSSARY.md` |
| 9 | Release one ships the four P0 views plus the value panel; the two P1 charts move to release 1.1 | The meeting is about the six patterns and the queue | R2 Q3 |
| 10 | All seven matching predicates and the description-date exception stay in release one | Dropping any one breaks a pattern in the evidence report | R2 Q4 |
| 11 | Import from a launch path; in-app picker and preview deferred | Same validation and provenance with less UI | R2 Q5 |
| 12 | Deferred to release two: saved views, 390 px layout, 50,000-row fixture, request timeout and cancellation, decision carry-forward | None is needed by the success criterion | R2 Q6 |
| 13 | Review notes and Oliver questions ship as Annotations keyed by ticket number, displayed on rule-generated Cases | Ticket numbers survive re-export; matching must not read them | R2 Q7 |
| 14 | Spec via `/to-spec`, tickets via `/to-tickets`, build test-first per ticket | The tickets become the record of what release one means | R2 Q9 |
| 15 | Interval confidence policy: Confident vs Ambiguous Interval with one documented Plausible Reading | Gives J its displayed afternoon overlap and B its "AM/PM absent" note without silent repair | R3 Q3 |
| 16 | Review Outcomes attach to ticket pairs, retained/replaced links to tickets, never to Case IDs | Rule changes recompose Cases and would orphan outcomes | R3 Q4, ADR 0004 |
| 17 | Release-one acceptance gate: section 12 data criteria 1-10, the three usability tasks via Explore controls, keyboard and 1440/1024 checks, measured timings; natural-language evaluation struck | Matches the release split | R3 Q5 |
| 18 | Second tab renamed Explore for release one | "Ask the data" would promise a prompt field that does not exist yet | R3 Q6 |
| 19 | Priority ties break on lowest Ticket Number; Case display ID derived from sorted member ticket numbers | Deterministic ordering and a readable identifier for meetings | R3 Q7 |
| 20 | Added the typed Time cells (132 int, 4 float, 2 datetime) to the verified observations | Found during independent verification; the parser contract must cover them | Verification |
| 21 | Screens use plain duplicate language: "Flagged duplicate" for Approved/Job 0, "Possible duplicate" for what the rules find, "Exact repeat, not flagged" for C-F, and outcomes Confirmed duplicate / Not a duplicate / Replacement ticket. Recorded Marker and Case are retired as terms; the ban on "duplicate" from entry 8 is lifted. "Paid twice" and "missed duplicate" stay off-limits | To Oliver, Approved with Job 0 is a flagged duplicate; arcane labels make the dashboard harder to read. The two banned phrases claim facts the export cannot show | Consultant, after R3 |
