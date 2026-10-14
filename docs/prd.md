# PRD: Labour Ticket Analytics

C.O. Williams Construction Ltd. | Version 1.1 | 14 October 2026 | Revised after the design review (grilling session)

Version 1.1 supersedes v1.0, kept unchanged at `docs/source/labour-ticket-analytics-prd-v1.0.md`.
Every change is listed in `docs/decision-log.md` with its reason and the ADR or review answer behind it.
Screens use the plain duplicate language Oliver uses (see "Display language" in section 3); `GLOSSARY.md` holds the full vocabulary.

## 1. Product decision

Build a small, local-first analytics application with two primary tabs: **Overview** and **Explore**.
It should turn a labour-ticket export into a useful review queue, explain processing and data-quality patterns, and let a nontechnical user build an auditable chart from a validated query plan.
Natural-language input for that plan is release two; see the release plan below.
Every result must lead back to the exact source rows.

The central question is: **Which records deserve attention, why, and what evidence would settle them?**
The application must distinguish what the spreadsheet records, what matching rules suggest, and what a person has verified.
It must not present an attractive chart of unsupported payment or fraud claims.

This is a proposed follow-up implementation to the original systems and AI discovery engagement.
That engagement covered investigation and recommendations, not production software.
Its budget and two-week discovery schedule are not an implementation commitment for this product.
Bid analytics, document search, and wider operational automation remain separate opportunities because this dataset cannot support them.

**Delivery standard:** a runnable application using the supplied workbook, not a static mockup, a hardcoded dashboard, or a chatbot that returns plausible numbers.
The external agent evaluated v1.0 before implementation; this revision records the outcome.

### Release plan

| Release | Contents | Gate |
|---|---|---|
| One | Import at launch; metric registry; all matching rules and the interval parser; the four P0 Overview views plus the value-context panel; evidence drawer with Annotations; local Review Outcomes; the Explore tab driven by deterministic plan controls | Section 12 data-correctness and usability criteria |
| 1.1 | The two remaining P1 Overview charts (claimed hours by job; submission and review timing) | Same tests extended |
| Two | Natural-language input on the Explore tab via a zero-cost local model (ADR 0001); in-app import with preview; saved views; decision carry-forward across Snapshots; 390 px layout; 50,000-row fixture; request cancellation and timeout; synthetic same-schema fixture | Section 12 natural-language evaluation |

The project is a prototype for one consultant preparing for a meeting with Oliver whose date is not yet scheduled.
It carries no model inference cost in any release.

## 2. Users and decisions

| User | Decision the product should support |
|---|---|
| Consultant / requester | Understand duplication patterns, prepare focused questions for Oliver, and identify which controls would help |
| Oliver and accounts reviewer | Find apparent repeated claims, inspect what happened to each ticket, and distinguish review gaps from recording gaps |
| Management | Understand the size and composition of the submitted workload, the unresolved processing queue, and the limits of the evidence |

The first release is a single-user desktop browser application for a trusted analyst using a local workbook.
That analyst is the consultant, on their own machine (macOS assumed, Python 3.12+ and Node 20+ present); the Oliver meeting is the forcing deadline.
Using it in a meeting is in scope; shared production access requires a separately reviewed deployment and access model.

Success means a user can identify the priority Peter Holder case, compare its source rows, and articulate the unresolved payment question without opening Excel.
They can also answer a new analytical question, change the grouping, and inspect the records behind a chart without writing code.

## 3. Evidence and business language

Use `labour-ticket-report-readable.md` as the accompanying evidence report.
It preserves the six discussion patterns, the requester's condensed review notes, and all 22 fields for the 29 example records.
Original example letters A-N are stable references, not a ranking or a set of mutually exclusive measured categories.

The workbook is `Labour Tickets Export.xlsx`, sheet `Labour Tickets (1)`.
Its SHA-256 is `36378ee04717f2432b9ec7e3a999d484da7dd8de43ff51869ba88a68047004fb`.
The supplied snapshot contains 2,836 records and 22 columns.

| Verified observation | Design implication |
|---|---|
| 2,611 Approved; 129 Pending; 96 Rejected | Show observed status, not inferred payment status |
| Approved splits into 2,462 Keyed true and 149 Keyed false | Approval and keying are separate dimensions |
| All 28 Approved / Job Number 0 records are also Keyed true | Keyed cannot safely mean that a valid payment was made |
| Every Ticket Number and ID is distinct | Repeated work can have different ticket identifiers; ID is not an employee ID |
| 142 employee labels after case/whitespace normalization | This is a count of labels, not verified people |
| 129 blank rates; 122 of those records have positive hours | Unknown labour value is not zero |
| Work dates include 2036 and 2050 | Date quality needs visible treatment before trend analysis |
| Time is free text, including multiple intervals and missing AM/PM | Matching must expose parsing confidence and preserve the original text |
| Time also holds typed cells: 132 integers, 4 floats and 2 datetimes beside 2,698 strings | The parser contract covers typed cells; raw zero stays zero, never midnight |
| No payment transaction, paid amount, paid date, or explicit duplicate-review outcome | Actual savings, paid duplicates, precision, and recall cannot be established from this export |

Oliver described Approved / Job Number 0 as a record that was “more than likely a duplicate.”
Call this a **flagged duplicate** on every screen: to Oliver, that is exactly what it is.
The flag is shown as a fact about what staff did; where the analysis disagrees, say so beside the flag, for example “Flagged duplicate · no matching ticket found.”
Do not label any ticket “paid twice”: the export holds no payment records.
Pending does not prove either that nobody reviewed a ticket or that a warning caught it.

Keep three separate facts throughout the product:

1. **Source state:** approval status, Keyed, and current Job Number.
2. **Analytical evidence:** matching fields, overlap, text variants, conflicting claims, and parsing uncertainty.
3. **Local review outcome:** Not reviewed, Confirmed duplicate, Not a duplicate, Replacement ticket, or Needs follow-up, with reviewer, date, note, and supporting reference.

A confirmed duplicate is still not a confirmed duplicate payment.

### Display language

The dashboard is for Oliver and accounts staff, so every label must be immediately clear to them.

| On screen | What it means |
|---|---|
| Flagged duplicate | Approved with Job Number 0: staff flagged the ticket as a duplicate |
| Possible duplicate | Tickets the analysis found that may repeat each other, opened and reviewed together |
| Exact repeat, not flagged | A possible duplicate where every claim field matches and no ticket is flagged |
| Confirmed duplicate | The reviewer agrees the tickets repeat the same claim |
| Not a duplicate | The reviewer judged the tickets to be separate work |
| Replacement ticket | One ticket corrects or replaces another; both are linked |
| Not reviewed / Needs follow-up | No judgement yet, or a question remains open |

Each possible duplicate states its reason in words, such as “same claim submitted twice,” “times overlap,” or “same task payment on both.”
Never shown: “paid twice,” “fraud,” or “missed duplicate,” because the export cannot show payment or whether a ticket was handled elsewhere.
Payment verification requires accounting evidence beyond this workbook.
Local review notes must never overwrite source values or imply a decision was made in the company's system.

## 4. Overview: highest-value analytics

### Information hierarchy

Lead with actionable counts and evidence, followed by processing and workload context.
Money is a small expandable context panel, not the headline.
Avoid a pie chart partitioning all tickets into “duplicates / not duplicates”; the evidence does not support that partition.

| Priority | View | What it answers | Representation and interaction |
|---|---|---|---|
| P0 | Review priorities | Which apparent repeats or conflicting claims warrant inspection? | Ranked case list beside a pattern-by-source-state count matrix; click opens comparison |
| P0 | Flagged duplicates | Which tickets did staff flag as duplicates, and can we identify the retained claim? | 28-record tile and filter; counterpart found / unresolved relationship shown separately |
| P0 | Processing queue | What is Pending, or Approved but not Keyed, and how old are those submissions? | Separate horizontal age-bucket bars; click reveals tickets and dates |
| P0 | Data readiness | Which records cannot be reliably compared or valued? | Compact issue counts for ambiguous times, anomalous dates, unresolved identity, missing rates, and missing required fields |
| P1 | Claimed work by job | Where are the reported hours concentrated? | Top-ten horizontal bars, explicit Other category, optional employee-label count or ticket count |
| P1 | Submission and review timing | Are claims entered late or awaiting disposition? | Weekly Created counts by current status; submission-lag distribution and observed approval-interval distribution |
| P1 | Value context | What is the scale of recorded claims and selected candidates? | Three small values with completeness note and formula, collapsed by default |

Release one ships all four P0 views and the P1 value-context panel.
The two remaining P1 charts ship in release 1.1; P0 still identifies build order within release one.

**Initial tiles:** 2,836 tickets; 28 flagged duplicates; 4 exact repeats not flagged, involving 8 Approved/Keyed tickets; 129 Pending; 149 Approved/not-Keyed.
Label the four as “exact repeats, not flagged,” never “missed duplicates”: whether staff caught them elsewhere is a question for Oliver.
Other rules will produce additional, less certain candidates.
The flagged tile counts tickets; the exact-repeat tile counts possible duplicates and shows its ticket count explicitly.
These tiles overlap conceptually and are not intended to sum to the population.

**Priority ordering:** unflagged exact repeats where all members are Approved/Keyed first, mixed Approved/Pending cases next, then pending conflicts and flagged duplicates with unresolved counterparts.
Within a tier sort by oldest Created timestamp; ties break on the lowest Ticket Number.
This is review priority, not a probability of wrongdoing.
Do not rank employees or supervisors by suspected fraud.

### Metric contract

Implement a versioned metric registry used by both tabs.
Each metric needs a stable ID, label, definition, unit, grain, allowed dimensions, null treatment, date basis, exclusions, and source-row lineage.
Each percentage must expose numerator and denominator.

| Metric ID | Definition and important limits |
|---|---|
| `ticket_count` | Number of source records in the active snapshot and filters; unique IDs are validated rather than assumed |
| `flagged_duplicate_count` | Approval Status = Approved AND numeric Job Number = 0; counts tickets, not confirmed duplicates |
| `unflagged_exact_repeat_count` | Strict equality groups defined in section 5, with no flagged duplicate and every member Approved/Keyed; counts groups |
| `candidate_ticket_count` | Distinct source records participating in the selected analytical rules; union records before counting |
| `pending_count` | Approval Status = Pending, regardless of Keyed value |
| `approved_not_keyed_count` | Approved AND Keyed = false; unknown Keyed is a separate quality issue |
| `pending_submission_age_days` | As-of date minus Created for currently Pending records; measures age since submission, not time since entering Pending |
| `approved_not_keyed_submission_age_days` | Same age definition for Approved/not-Keyed; do not call this time awaiting keying |
| `claimed_hours` | Regular Hours + Overtime + Double Time, with no pay multipliers; invalid/missing components produce a coverage warning, not silent zero |
| `employee_label_count` | Distinct normalized employee labels; verified aliases can produce a separately named person measure later |
| `submission_lag_days` | Calendar Created date minus Date, only when both dates are usable; negative values are a separate exception, not silently discarded |
| `observed_approval_interval_hours` | Date Approved minus Created for Approved records with valid nonnegative timestamps; not stage duration, and never applied to Rejected records as approval time |
| `known_base_value_bbd` | Recorded Rate × claimed hours + Job Work Pay, rounded half-up to cents per ticket; sum available components and disclose unpriced labour |

For the default job-hours view use Approved, nonzero-job tickets, and state that scope in its title.
Show reported hours as recorded, including possible repeats; offer an explicit analyst-reviewed alternative only when retained-ticket decisions exist.
The dataset does not measure productivity, attendance compliance, budgets, project profitability, or actual expenditure.

Default to all dates for totals so imports reconcile.
For date trends, require a displayed date basis: Created, Date as recorded, or Date Approved where meaningful.
Show out-of-range dates separately using a visible configurable reporting window; no silent correction or automatic reassignment of a year.
The original export timestamp is unavailable, so use 8 October 2026 as a clearly labeled analytical as-of assumption for this fixture, based on the latest Created date.
Let the analyst change it; never quietly age this old snapshot using today's date.
Do not interpret current-status-by-Created charts as a historical record of status transitions or as complete company-wide activity.

## 5. Duplicate and exception model

### Rules grounded in the review

These six patterns describe evidence and workflows; several can apply to one case.
Store each rule match separately, with a reason and exact fields compared.
Confidence means strength of matching evidence, not confidence that someone was paid or acted deliberately.

| Pattern | Examples and source rows | First-release handling | Question the case should help settle |
|---|---|---|---|
| 1. Same claim appears twice | C Peter 620/855; D Latoya 974/1868; E Samantha 1309/1656; F Mario 2206/2351 | Strict matching groups; prioritize unflagged Approved/Keyed exact repeats | Missed, handled elsewhere, or excluded before payment? |
| 2. Same claim looks different as text | G Kerriann 82/103; H Mario 829/1072 | Normalize time syntax; propose name aliases without silently merging identities | Did the existing warning see these, and what happened next? |
| 3. Possible correction or resubmission | J Orlando 61/105; I Damar 318/1545/999; K Errol 2188/2187 | Flag overlaps and changed claim fields; show chronology and supervisor changes | Which claim is valid, and can a replacement leave two active claims? |
| 4. Equal duration, separate periods | B Patrick 33/79; A Romarian 591/593; L Weston 2151/2152 | Explain non-overlap when time interpretation is reliable; retain ambiguous cases for review | Does the current process distinguish separate work, and what is the intended submission unit? |
| 5. Repeated payment component | M Weston 1575/2149 | Flag matching Job Work Pay as a component comparison, not proof of a repeated whole ticket | Why are both flagged, and where is the valid entitlement? |
| 6. Service date in description | N Toyna 1727/1728 | Surface conflict between Date and explicit date references; retain text and uncertainty | Which service date and earlier claim history should the check use? |

**Strict equality baseline:** group by Employee after trim/case-fold/collapse-whitespace, Date as recorded, Job Number, Time after the same basic text normalization, and the four claim components Regular Hours, Overtime, Double Time, Job Work Pay.
Do not include ticket ID, creation timestamps, approval timestamp, supervisor, or description in this baseline key.
Those fields provide review evidence and can differ between otherwise repeated claims.
Do not collapse the four hour/payment components into a single monetary value for matching.

This baseline yields 34 groups of two records in the supplied sample.
Four groups have both tickets Approved/Keyed and nonzero jobs; one is Pending/Pending; one is Approved/Pending; 28 have at least one Rejected member.
The last 28 are not proof of correct duplicate rejection: the reason for rejection is absent.
The four priority groups are C-F and must emerge from the rule, not a hardcoded list of names or row numbers.

**Time-aware matching:** retain raw Time plus parsed intervals, parser version, parse status, and assumptions.
Support common AM/PM variants, punctuation, whitespace, 24-hour time, and multiple intervals such as L's underscore-separated periods.
For unambiguous intervals use half-open ranges, so one period ending when another begins is not an overlap.
Compare the union of intervals, not just first start and last end.
Missing AM/PM, implausible durations, reversed endpoints, and possible overnight shifts must not be silently repaired.
Return a plausible interpretation for review if useful, but do not call the work definitely separate on that basis.

**Interval confidence policy.** A period with explicit AM/PM or in 24-hour form is a Confident Interval.
A period without a meridiem is an Ambiguous Interval; it carries one Plausible Reading under the documented working-day interpretation: a start between 5:00 and 11:59 is taken as AM and one from 12:00 to 4:59 as afternoon, and an end numerically below the start as PM, always labelled "assumed."
Only Confident Intervals can establish overlap or separation; Ambiguous Intervals can only produce the ambiguous-period comparison.
Multiple periods in one cell split on underscore, slash, ampersand, "and", and commas.
An overlap indicates conflicting work claims, not necessarily a duplicate whole invoice or a known excess value.
Do not equate elapsed clock time to paid hours without an agreed break rule.

**Identity:** exact normalized names provide a provisional matching key, not proof of identity.
Space-stripped/fuzzy name comparisons propose aliases such as Mario Collymore / Mariocollymore; a reviewer confirms or rejects them.
Email is supporting evidence only: the sample contains shared emails across different employee names.
Occupation changes must not automatically split a person's history or prove identity fraud.

**Dates and job identifiers:** same employee/date is a candidate search space, not a duplicate rule.
Allow cross-job comparisons for overlap and replacement investigations.
An overwritten Job Number 0 cannot reveal the original job; do not require the flagged ticket's current job number to match its counterpart.
Never recover an original job number as fact merely from matching Job Name.
Description dates can suggest a discrepancy but cannot overwrite Date automatically.

**Cases and counting:** maintain source records, pairwise relationships, and review cases separately.
For general matching, a case is a connected set of candidate relationships within an employee/date context, with every edge visible.
Transitive connectivity does not mean all members repeat one another.
A Possible Duplicate's display identifier is derived from its sorted member ticket numbers (for example "Possible duplicate L225526+L225761"), so it is stable across runs of one Snapshot and readable aloud in a meeting; it is not a storage key.
For example, a long claim may overlap two legitimate separate shifts; the app must not assume only one ticket can survive.
Strict equality groups can use `n - 1` only as an explicitly hypothetical redundant-record count.
Do not apply that formula to general overlap components.

Pattern filters are multi-label and must say their counts overlap.
A distinct-case total uses union case IDs; a distinct-ticket total uses union source IDs.
Possible duplicates with mixed statuses retain their member-level breakdown instead of being forced into “paid / unpaid.”
Only reviewed retained/replaced relationships support exclusion from an adjusted claim total.

### Conservative first-release predicates

Apply the following rules to all records, without hardcoding the example rows.
Missing or invalid comparison fields cannot satisfy equality by being treated as zero or an empty string.
Rules may share records and must expose their individual reasons.

| Rule | Minimum condition and output |
|---|---|
| Strict repeat | The complete strict key above matches; return an equality group, subject to source-state filters |
| Time-text variant | Same normalized employee, Date, Job Number, and four claim components; Time differs as text but parses to identical unambiguous interval sets, or differs only in spacing/case/punctuation around an otherwise identical time token sequence; disclose which condition matched |
| Name-space variant | Names match after removing whitespace and case-folding, and Date, Job Number, normalized Time, and four claim components match; propose an alias relationship but do not merge employee keys |
| Work-period conflict | Same normalized employee or confirmed alias and same Date, with a positive intersection of confidently parsed interval sets; allow different jobs and claim components |
| Ambiguous-period comparison | Same employee, Date, and nonzero job, with matching four claim components and distinct unresolved Time strings; surface for time review without claiming overlap until the interpretation is confirmed |
| Flagged-duplicate counterpart | At least one record is a flagged duplicate; same employee or confirmed alias and Date, plus either the same complete claim-component vector, identical confidently parsed periods, or identical nonempty unresolved Time text and identical nonempty description after basic case/whitespace normalization; the last path is an uncertain counterpart comparison, as in K; ignore current job equality and return all plausible counterparts, not an automatically selected original |
| Repeated component | Same employee or confirmed alias, same Date, equal positive Job Work Pay, and either the same nonzero job or at least one Job 0; label a low-confidence component comparison, not a duplicate entitlement |
| Description-date exception | An explicit service-date reference in description differs from Date; preserve the extracted text span and interpretation, flag an omitted year as uncertain, and do not create a duplicate edge solely from this exception |

General fuzzy-name matching and semantic description similarity are deferred until they can be evaluated against reviewed labels.
Descriptions and supervisor differences still appear as review evidence.
Rules produce an explainable candidate queue; they do not establish every possible duplicate or true detection accuracy.

### Local review controls

The evidence drawer lets a user choose a local Review Outcome, enter a note/reference, confirm or reject a proposed Alias, and link a replaced ticket to one or more retained tickets.
A Review Outcome attaches to the order-independent pair of Tickets behind a Candidate, and a retained/replaced link attaches to individual Tickets; a Possible Duplicate displays the outcomes of its member pairs and is never the key (ADR 0004).
Do not force a single retained ticket when the evidence supports several legitimate periods or components.
Saving or revising a decision records reviewer label, timestamp, previous value, new value, and rationale in local history.
Require an explicit retained/excluded relationship before affecting an adjusted total; an unresolved note alone has no numerical effect.
Decisions are snapshot-scoped by default.
Carry-forward to a new export is release two: proposed carry-forwards will require matching ticket numbers and comparison of relevant source values, followed by explicit revalidation; never silently apply old decisions to changed records.

## 6. Overview design and evidence inspection

Use an understated analytical workspace: off-white background, dark ink, a restrained teal accent, amber for unresolved evidence, and red reserved for errors or explicitly conflicting records.
Use a readable system sans-serif, tabular numbers, generous spacing, direct chart labels, and minimal ornament.
Do not rely on color alone or use green to imply payment was verified.

```text
LABOUR TICKETS          Workbook / snapshot / as-of assumption     Import
Overview | Ask the data                 Definitions | Saved views

Date basis [Created]  Range [All]  Job [All]  Status [All]  Clear
Tickets 2,836 | Flagged duplicates 28 | Exact repeats not flagged 4 / 8 tickets | Pending 129

REVIEW PRIORITIES                         PROCESSING QUEUE
Pattern / evidence / member states       Pending submission age
Peter Holder ... [Compare]               Approved, not keyed: age
Mario name variation ...                 [View rows]

CLAIMED HOURS BY JOB                     DATA READINESS
Top 10 + Other                           Ambiguous times / dates / rates

Submission and review timing             [Value context, expandable]
```

Selecting a case opens a wide evidence drawer with a concise reason, claim timeline, and side-by-side transposed source table.
Keep the field-name column fixed and highlight differing values.
Preserve all 22 source columns, including whitespace and description line breaks; blank, zero, and false must remain distinguishable.
Show Excel row and original dataframe index, workbook fingerprint, and sheet.
Offer an optional “show whitespace” display for G/H, without altering the source text.
Show original review notes and Oliver questions alongside their examples, not in a disconnected question appendix.
They ship as Annotations in a small file keyed by ticket number carrying the A-N letter, the condensed note, and the Oliver question; the drawer displays them when a rule-generated Possible Duplicate contains those Tickets, and matching never reads them.
F must explicitly remain distinguishable from H, although both involve Mario.

Every chart supports View data and source-row drilldown, with aggregation grain and active filters visible.
Show total contributing records and any excluded or unpriced records.
Filters may select a possible duplicate because one member matches; then show all members, with out-of-filter members labeled so comparisons are not truncated.
Aggregate ticket charts still use only in-filter tickets, not those added for comparison context.
Saved views are release two; when added they retain their snapshot, filter state, metric/rule versions, and reviewed alias configuration.

Keyboard navigation, visible focus, accessible table alternatives, labeled controls, and legible chart contrast are required.
At narrow widths stack panels and scroll evidence tables horizontally rather than clipping cells; the 390 px layout is verified in release two.
Loading, empty-result, invalid-import, stale-snapshot, uncertain-parse, and failed-query states must explain the next action in ordinary language.

## 7. Explore: query-plan charts, with natural language in release two

In release one the tab is named **Explore** and is driven entirely by the editable metric, grouping, filter, date-basis and chart chips described below, which compile to the same validated query plan.
There is no prompt field, no model, and no inference cost (ADR 0001).
Everything in this section that depends on interpreting a sentence (the prompt field, the one-sentence interpretation, follow-ups, clarification, the example-query table, and the held-out evaluation) is the release-two contract, retained here so the plan schema is designed for it from the start.
The intended release-two provider is a local open-weights model behind the provider adapter; nothing is built for it in release one.

### Research-informed direction

Research checked on 14 October 2026 suggests four useful patterns for this product.
This is a review of documented product capabilities, not a claim that any vendor is the best-performing system.

| Reference | Documented approach | Requirement adopted here |
|---|---|---|
| [Looker Conversational Analytics](https://docs.cloud.google.com/looker/docs/conversational-analytics-overview) | Business definitions and field selection are grounded in a semantic model and agent instructions; verified queries provide examples | Central metric registry, approved dimensions, and tested question-to-plan examples |
| [Power BI verified answers](https://learn.microsoft.com/en-us/power-bi/create-reports/copilot-prepare-data-ai-verified-answers) | Human-approved visual answers can be associated with phrases and filters | Curated starter questions, reusable verified plans, and visible filter interpretation |
| [Tableau Agent](https://help.tableau.com/current/pro/desktop/en-us/desktop_einstein.htm) | Natural language can build, filter, and refine visual analyses alongside ordinary authoring controls | Conversation plus editable chart controls; users need not find perfect wording |
| [Vega-Lite specification](https://vega.github.io/vega-lite/docs/spec.html) | Declarative JSON describes visual encodings and composed views | Generate charts through validated, limited specifications rather than arbitrary executable code |

These sources support the interaction patterns above; the architecture below is our recommendation for this dataset.
The objective is grounded question-to-chart execution, not unrestricted autonomous analysis.

### Interaction contract

The tab starts with six useful example questions, a prompt field, and a visible dataset/filter context.
The result contains: a one-sentence interpretation, editable metric/grouping/filter chips, a chart, a table alternative, and a collapsed “How this was calculated” panel.
The panel shows formulas, exclusions, source-row references, and query-plan details, not private model reasoning.

Support follow-ups such as “only September,” “split that by job,” and “make it a bar chart.”
Resolve relative dates against the displayed analytical as-of date and show the resulting absolute range.
Do not silently carry a job filter or date basis across a fresh conversation.
On entering the tab, offer “Use Overview filters” or “Start with all data”; keep the choice visible.
Changing snapshots invalidates results until rerun.

Clarify only when ambiguity materially changes the answer.
For “duplicates by supervisor,” ask whether the user means flagged duplicates, possible duplicates, or confirmed duplicates.
For “money lost to duplicates,” explain that payment evidence is missing and offer the labeled base-value scenario.
Do not substitute an easier question silently.
If no supported interpretation exists, show a clear limitation and relevant alternatives rather than inventing a graph.

Support bars, time series, histograms, scatterplots, and tables in the first release.
Use bars for categories, lines for ordered dates, and histograms for distributions.
Do not use a line chart to connect unordered job names or truncate bar baselines.
High-cardinality charts default to top ten plus Other and expose the full table.
An empty result is not a zero-valued trend.

```text
ASK THE DATA                    Snapshot / filters / date basis
[Show pending tickets by supervisor as a horizontal bar chart]

Interpreted as: count tickets with Status = Pending, by Supervisor
[Metric: Tickets] [Status: Pending] [Group: Supervisor] [Chart: Bar]

                         CHART
[View table] [Inspect source rows] [How calculated] [Save] [Export]

Follow up: [Only those submitted more than seven days ago...]
```

### Example queries and expected behavior

| Query | Expected chart / behavior |
|---|---|
| Show ticket counts by approval status. | Bar chart: 2,611 Approved, 129 Pending, 96 Rejected with all-data filters |
| Show approved tickets split by keyed status. | Bar chart: 2,462 true and 149 false |
| Show the exact repeats that were not flagged, by employee. | Four bars for C-F labeled “exact repeats, not flagged”; drilldown contains eight tickets |
| Compare flagged duplicates with exact repeats that were not flagged. | Separate panels or explicitly labeled units: 28 flagged tickets versus four possible duplicates; no additive pie |
| Which pending tickets have waited longest? | Sorted table of age since Created as of the selected date, with optional age histogram |
| Make a bar chart of pending tickets by supervisor. | Ticket-count bars; no claim about supervisor performance or who caused a delay |
| Show claimed hours for the ten busiest jobs. | Explain “busiest” as most claimed hours, use the documented Approved/nonzero default, display Other and scope |
| Plot weekly submissions, split by current approval status. | Created-week stacked bars; clearly a current-status snapshot grouped by submission week |
| How long after the work date are tickets submitted? | Submission-lag histogram; negative and anomalous-date records disclosed separately |
| Show dates that need checking. | Exception table with raw Date, Created, reason, and source rows; not an automatically repaired timeline |
| Compare the two Mario Collymore cases. | Separate September 10 F and September 23 H evidence views; do not combine them |
| How much was paid twice? | State that actual payment is unavailable; offer the four-case BBD 571.37 base-value scenario without presenting it as paid |
| Only include September, then change the last chart to a bar chart. | Preserve the prior metric and explicit date basis, show September 2026 filter; clarify if no prior result exists |
| Which employees are least productive? | Explain that output/productivity data is absent; offer reported hours only if the user chooses it |

### Execution contract

The model proposes a typed query plan, not the answer's numbers.
Example:

```json
{
  "metric_id": "ticket_count",
  "group_by": ["Supervisor"],
  "filters": [{"field": "Approval Status", "operator": "eq", "value": "Pending"}],
  "date_basis": "Created",
  "date_range": null,
  "chart": "bar_horizontal",
  "sort": "metric_desc",
  "limit": 10,
  "include_other": true
}
```

Attach snapshot ID, semantic/rule versions, and inherited filters outside the model's control.
Validate every field, operator, metric, chart encoding, limit, and aggregation against an allowlist.
Compile the plan into parameterized read-only queries and calculate results deterministically.
Generate the chart through trusted templates, with no external data URLs or arbitrary expressions supplied by the model.
Disallow arbitrary model-generated Python, JavaScript, SQL execution, filesystem operations, and network requests.
Unknown columns, impossible joins, excessive limits, and unsupported metrics produce a recoverable validation error.
Source descriptions and user queries are untrusted content, never instructions to bypass these controls.

Return computed values, source lineage, and validation warnings; any generated narrative must be consistent with that returned result.
Cache by snapshot, plan, filter state, semantic version, and review configuration, not by prompt alone.
Allow a user to correct the interpretation without retyping the whole question.

## 8. Import, storage, and privacy

Accept `.xlsx` exports with the supplied schema first; do not advertise support for arbitrary spreadsheets.
Release one imports the workbook from a path given at launch and shows the Snapshot fingerprint, sheet, row count and import issues in the header; the in-app file picker with sheet preview and column-mapping review is release two.
Preserve raw cell values and types, date formatting metadata where relevant, source row numbers, original order, and workbook fingerprint.
Read data without executing formulas, macros, links, or embedded content.
Missing required columns block activation with a specific mapping error; missing optional fields disable dependent metrics with an explanation.
Validate ticket ID uniqueness and numeric/date types rather than silently dropping bad rows.

The required column set is Employee, Ticket Number, Job Number, Date, Time, Regular Hours, Overtime, Double Time, Job Work Pay, Approval Status, Keyed, and Created.
The remaining columns are optional for activation but preserved when present: Occupation, Job Name, Description of Job Work, Modified, ID, Email Address, Rate, Date Approved, Supervisor, and Modified By.
Missing descriptions disable description-date checks; missing Supervisor disables that grouping; missing Rate or Date Approved disables the corresponding dependent calculations where needed.

Text columns remain raw strings; accept numeric job identifiers without grouping separators, numeric hours/pay/rates, true/false booleans, Excel dates, and unambiguous ISO date strings.
Preserve raw zero in Time as zero rather than interpreting it as midnight.
Do not guess locale-dependent date strings or coerce unknown status/boolean values.
Invalid individual cells and duplicate/missing business IDs remain visible records with issue flags; dependent rules and metrics exclude only the unusable calculation and disclose coverage.
Only an unreadable workbook, missing required column mapping, or absent data sheet blocks activation.
Source-row provenance remains valid even when business identifiers are defective.

One active snapshot at a time is sufficient for the first release.
Reimporting an identical workbook must be idempotent.
A newer export is a separate snapshot, not extra tickets appended to the old file.
Source provenance key = snapshot + sheet + Excel row; business ticket IDs are separate fields.
Never merge different employee names solely because they share an email.

Store raw tickets, normalized fields, parse results, relationship edges, review cases, local decisions, saved queries, and versioned configuration separately.
No source edits or writeback to SharePoint, Power Apps, accounting, or payroll are in scope.
Render cell content as text, never HTML; protect CSV exports from spreadsheet formula injection while leaving the stored raw value intact.

Keep workbook processing and aggregates local by default.
The source workbook is committed to this private repository under `data/` so cloud sessions and the real-row tests can use it; it must be purged from history before the repository is ever made public (ADR 0003).
Release one ships the provider adapter with a null provider only.
Release two uses a local open-weights model at zero inference cost; a hosted paid API is out (ADR 0001).
The original engagement restricts confidential information from unapproved AI services; no provider should receive the workbook automatically.
Prefer sending metric definitions, schema, and the query, with minimum necessary value-resolution results.
Names, emails, descriptions, queries containing personal data, and query results require the same approved data-handling policy.
Store credentials outside browser code and redact sensitive content from logs.
The initial local service must bind to loopback, not expose an unauthenticated network service.

In release one the deterministic plan controls are the Explore feature, not a fallback, and are accepted on the section 12 usability tasks.
In release two, a configured local provider must pass the end-to-end query tests for the natural-language feature to be accepted.

## 9. Small value panel

Currency is Barbados dollars, displayed as **BBD**.
Use all recorded hour categories at the recorded regular Rate plus Job Work Pay.
Do not investigate overtime or double-time multipliers, payroll rules, or premium-rate scenarios in this project.
Keep the original hour columns for matching and evidence.

With all source records selected, including Rejected:

| Measure | BBD | Interpretation |
|---|---:|---|
| Known base-value components | 341,477.32 | Partial valuation of submissions, not total paid or total liability |
| Base value of 28 flagged duplicates | 3,399.71 | Value of tickets staff flagged as duplicates, not verified savings |
| One extra claim per strict pair C-F | 571.37 | Hypothetical excess if one whole claim per pair was unnecessary, not confirmed loss |

The missing-rate labour is 881 hours across 122 Pending tickets.
Known Job Work Pay on those records remains included in the known-component total.
Do not substitute a zero rate, infer a rate from another person, or sum flagged and unflagged scenarios as total savings.
Do not calculate general overlap-case excess without identifying retained entitlements and repeated components.

## 10. Consequential questions for Oliver

The product can be implemented using qualified labels before these are resolved.
Do not block basic descriptive analytics on an unanswered business question.
Answers should update a documented semantic configuration and, where necessary, future scope.

| Clarification | Examples | What changes after the answer |
|---|---|---|
| Which checks are automated, what does the red warning do, and where is the human disposition saved? | C, G, H | Whether the gap is matching, workflow enforcement, or observability |
| Does Approved/Job 0 always mean a duplicate, and how is the retained ticket/payment linked? | I, K, M | Flag interpretation and validated outcomes, including potential incorrect exclusions |
| What do Keyed, Pending, and Modified By mean operationally? | C, H, J | Processing labels and what can be inferred from the export |
| Can workers correct, cancel, or resubmit to a different supervisor? | J, I | Replacement relationships and cross-reviewer visibility |
| Is submission intended per day, per job, or per work period? | B, A, L | Validation rules and the form structure that would prevent ambiguity |
| What does Date represent for retrospective task claims? | N | Service-date matching and which additional history is needed |
| Is a reliable employee ID available outside this export? | H | Identity resolution and reduction of uncertain name matching |

Pay rates and harmless formatting preferences are not meeting priorities unless they change claim identity or detection.
Name and time input controls are likely improvements, but validate what Oliver has already enforced before proposing replacement forms.

## 11. Suggested implementation and scope boundary

Architecture (ADR 0002): a Python data service using openpyxl and DuckDB, with a React/TypeScript interface and a constrained Vega-Lite chart renderer, packaged as one process that serves the built frontend, binds to loopback, and launches with a single command taking the workbook path.
The database owns calculations and provenance; in release two the model only translates intent into a validated plan.
Local Review Outcomes, Aliases and their history live in one local DuckDB file beside the imported Snapshot, in tables physically separate from source Tickets.
Package a documented local launch path so the reviewer does not need a notebook or multiple manual setup steps.
Pin versions and record the environment needed to reproduce results.

The stack was accepted in review and is recorded in ADR 0002; a BI platform was not chosen because the evidence drawer and Review Outcome model need custom handling.

Out of scope: live source integrations, automatic rejection/approval, payment blocking, payroll calculations, guaranteed employee resolution, predictive fraud scores, worker productivity scoring, company-wide ROI claims, and multi-tenant deployment.
Later work could add stable employee IDs, explicit duplicate/correction links, actual payment reconciliation, and source-system decision capture.
Those additions would permit stronger outcome metrics than this snapshot supports.

## 12. Acceptance and evaluation

### Data and analytical correctness

1. Import the supplied workbook and reproduce 2,836 rows, 22 fields, all status/keyed counts, and 28 flagged duplicates without hardcoded summary values.
2. Reproduce the strict baseline's 34 two-record groups and the four priority C-F cases; show reasons and member states.
3. Preserve all 638 source-cell values in the report's 14 comparisons, including the F/H distinction and G's whitespace difference.
4. For A, identify separate intervals; for B, surface absent AM/PM assumptions; for L, parse the interval union without a false overlap across the middle gap.
5. For J, surface the ambiguous-period comparison and show its apparent overlap under a displayed afternoon interpretation; do not assert resolved overlap from missing AM/PM or treat Orlando's separate morning HR ticket, row 137, as the same work solely because its hours match.
6. For H, show the Pending record was created before the Approved record; for M, show that the no-hours record was created later, not an earlier incomplete submission.
7. For I, include Rejected row 999 as context linking descriptions; for N, preserve the distinct dates in description and avoid declaring duplication on Date alone.
   For K, produce an uncertain flagged-duplicate counterpart relationship despite changed hour components, preserving the unresolved AM/PM interpretation.
8. Test a three-ticket case where one interval overlaps two non-overlapping intervals; do not infer that two records are redundant merely from connectivity.
9. Reconcile BBD 341,477.32, 3,399.71, and 571.37 under the stated formula; show missing-rate coverage and never label these as actual payments.
10. Verify that every graph's drilldown reproduces its total and honors the same filters, snapshot, and metric version.

### Natural-language evaluation (release two)

Build a small held-out suite before tuning the prompt: the 14 examples above, at least two meaning-preserving paraphrases of each, and additional adversarial/ambiguous prompts.
Separate expected semantic plans and numerical answers from screenshots or subjective model judgments.
Include follow-up scope changes, unsupported payment claims, shared-email identities, unknown fields, prompt injection inside source descriptions, invalid model output, empty results, and provider failure.

All 14 canonical questions must yield the intended plan/result or intended clarification.
At least 90% of held-out supported paraphrases must yield the correct plan and exact deterministic aggregates.
All safety/semantic guard cases must pass: no fabricated payment status, silent identity merge, source mutation, arbitrary execution, or unauthorized data transfer.
Report numerator, denominator, failed examples, provider/model configuration, and rerun variability; do not call this a production accuracy guarantee.

### Usability and performance

A nontechnical reviewer must complete three tasks without SQL or Excel: investigate C, compare F with H, and create then refine a pending-by-supervisor chart using the Explore controls.
Each task must expose its source evidence and assumptions without searching another report section.
Test keyboard use and layouts at 1440 and 1024 CSS pixels; 390 is release two.

On the documented reference machine, target first workbook load under 10 seconds and ordinary filter/drilldown responses under 1 second at the supplied size.
In release two, test a synthetic 50,000-row same-schema dataset with a target of under 30 seconds import and under 2 seconds ordinary aggregation; keep generated fixture results separate from real findings.
In release two, natural-language requests show progress immediately, allow cancellation, and time out with a recoverable state after 60 seconds.
Report measured performance rather than claiming these targets were met without a run; release one reports measured load and filter times only.

## 13. External-agent handoff

The review is complete; its outcome is this revision, `docs/decision-log.md`, `GLOSSARY.md` and `docs/adr/`.
Release one is specified with `/to-spec`, broken into GitHub Issues with `/to-tickets` under the configured triage labels, and built ticket by ticket test-first.

Deliver the application, setup/run instructions, source and pinned dependencies, metric/rule documentation, evaluated query fixtures, and a test report with unresolved limitations.
Include the final PRD version, a brief decision log, and screenshots showing both tabs and an expanded source comparison.
Do not publish employee records in a public repository or hosted demo; the private repository holds the workbook under ADR 0003.

Suggested build sequence:

1. Import from a launch path with immutable provenance; reconcile counts and valuations.
2. Interval parser and confidence policy; strict matching and the remaining rules; metric registry.
3. Evidence drawer with Annotations and Review Outcomes; the Peter Holder walkthrough works end to end.
4. Overview P0 views, value panel, filters; Explore tab with plan validation, deterministic execution and chart editing.
5. Real-row acceptance tests, keyboard and layout checks, single-command packaging, measured timings.
6. Release 1.1: the two P1 charts. Release two: natural-language layer and the deferred list.

The first review gate is data correctness and qualified business language.
The final gate is a usable dashboard and natural-language chart experience that can explain every result through the supplied records.
