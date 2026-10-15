# Metrics and matching rules

Generated from the running service by `tests/test_reference_docs.py`; do not edit by hand.
Registry 1.7.0, rules 1.4.0, parser 1.0.0, app 0.1.0.
Every Overview tile, chart and Explore plan reads its numbers from these metrics, and every possible duplicate comes from these rules.

## Metrics

### `ticket_count`: Source records

Number of Tickets in the active Snapshot under the active filters. Every source row counts once, including rows with import issues; unique IDs are validated at import rather than assumed.

| Property | Value |
|---|---|
| Unit | tickets |
| Grain | Ticket |
| Statistic | count |
| Allowed dimensions | Approval Status; Keyed; Job Number; Job Name; Supervisor; Occupation |
| Null treatment | Every Ticket counts, whatever its cells hold. |
| Date basis | Totals cover all dates unless a date range is set; a range always names its date basis. |
| Exclusions | none |
| Lineage | One per Excel row of the data sheet in the active Snapshot. |
| Percentage of | none |
| Requires columns | none |
| Buckets | none |
| Reads review links | no |

### `flagged_duplicate_count`: Flagged duplicates

Tickets staff flagged as duplicates by approving them with Job Number 0: Approval Status is Approved and Job Number is the number 0. Oliver described these as “more than likely a duplicate”; the flag is a fact about what staff did, and the count asserts nothing about whether the analysis agrees or about payment. It counts Tickets, not Confirmed Duplicates.

| Property | Value |
|---|---|
| Unit | tickets |
| Grain | Ticket |
| Statistic | count |
| Allowed dimensions | Approval Status; Keyed; Job Number; Job Name; Supervisor; Occupation |
| Null treatment | An invalid Approval Status or a Job Number that is not a whole number never matches. |
| Date basis | Totals cover all dates unless a date range is set; a range always names its date basis. |
| Exclusions | Tickets with any other status or job |
| Lineage | Each Approved Ticket whose Job Number cell holds 0. |
| Percentage of | `ticket_count` |
| Requires columns | none |
| Buckets | none |
| Reads review links | no |

### `unflagged_exact_repeat_count`: Exact repeats, not flagged

Possible duplicates found by the Strict repeat rule (normalized Employee, Date as recorded, Job Number, normalized Time and all four hour and pay amounts match) in which no Ticket is a flagged duplicate and every Ticket is Approved and Keyed. Counts possible duplicates, not Tickets; whether staff handled them somewhere the export cannot show is a question for Oliver, so they are not called missed.

| Property | Value |
|---|---|
| Unit | possible duplicates |
| Grain | Possible duplicate |
| Statistic | count |
| Allowed dimensions | none |
| Null treatment | A missing or invalid comparison field never satisfies equality, so that Ticket is never in a group. |
| Date basis | Totals cover all dates unless a date range is set; a range always names its date basis. |
| Exclusions | Possible duplicates holding a flagged duplicate; Possible duplicates with any Ticket not Approved and Keyed; Tickets with a missing or invalid comparison field, which are reported |
| Lineage | Each possible duplicate lists its member Tickets by Excel row. |
| Percentage of | none |
| Requires columns | none |
| Buckets | none |
| Reads review links | no |

### `candidate_ticket_count`: Candidate Tickets

Distinct Tickets taking part in at least one Candidate from the matching rules built so far; Tickets are unioned before counting.

| Property | Value |
|---|---|
| Unit | tickets |
| Grain | Ticket |
| Statistic | count |
| Allowed dimensions | Approval Status; Keyed; Job Number; Job Name; Supervisor; Occupation |
| Null treatment | A Ticket counts once however many rules or Candidates it appears in. |
| Date basis | Totals cover all dates unless a date range is set; a range always names its date basis. |
| Exclusions | none |
| Lineage | Each Candidate names its two Tickets by Excel row. |
| Percentage of | `ticket_count` |
| Requires columns | none |
| Buckets | none |
| Reads review links | no |

### `pending_count`: Pending

Tickets whose Approval Status is Pending, whatever their Keyed value. Pending does not prove that nobody reviewed a Ticket or that a warning caught it.

| Property | Value |
|---|---|
| Unit | tickets |
| Grain | Ticket |
| Statistic | count |
| Allowed dimensions | Approval Status; Keyed; Job Number; Job Name; Supervisor; Occupation |
| Null treatment | An invalid Approval Status never matches. |
| Date basis | Totals cover all dates unless a date range is set; a range always names its date basis. |
| Exclusions | Approved and Rejected Tickets |
| Lineage | Each Ticket whose Approval Status cell is Pending. |
| Percentage of | `ticket_count` |
| Requires columns | none |
| Buckets | none |
| Reads review links | no |

### `approved_not_keyed_count`: Approved, not Keyed

Tickets whose Approval Status is Approved and whose Keyed cell is false.

| Property | Value |
|---|---|
| Unit | tickets |
| Grain | Ticket |
| Statistic | count |
| Allowed dimensions | Approval Status; Keyed; Job Number; Job Name; Supervisor; Occupation |
| Null treatment | A Keyed cell that is not true or false is a separate import issue and never counts as false. |
| Date basis | Totals cover all dates unless a date range is set; a range always names its date basis. |
| Exclusions | Tickets that are not Approved; Approved Tickets with Keyed true or unknown |
| Lineage | Each Approved Ticket whose Keyed cell is false. |
| Percentage of | `ticket_count` |
| Requires columns | none |
| Buckets | none |
| Reads review links | no |

### `pending_submission_age_days`: Pending: age since submission

The as-of date minus the calendar date of Created, in whole days, for currently Pending Tickets. This is age since submission, not time spent waiting in the current state.

| Property | Value |
|---|---|
| Unit | days |
| Grain | Ticket |
| Statistic | median |
| Allowed dimensions | Approval Status; Keyed; Job Number; Job Name; Supervisor; Occupation |
| Null treatment | A Ticket with an unusable Created date is excluded and counted, never aged from zero. |
| Date basis | measured on Created to the analytical as-of date; Totals cover all dates unless a date range is set; a range always names its date basis. |
| Exclusions | Created is missing or not a date; Created falls after the as-of date: such a Ticket is left out and reported, never aged as zero |
| Lineage | One value per Pending Tickets Ticket, from its Created cell and the as-of date. |
| Percentage of | none |
| Requires columns | none |
| Buckets | `0`: 0 days; `1`: 1 day; `2`: 2 days; `3`: 3 days; `4-6`: 4–6 days; `7-13`: 7–13 days; `14-29`: 14–29 days; `30-or-more`: 30 days or more |
| Reads review links | no |

### `approved_not_keyed_submission_age_days`: Approved, not Keyed: age since submission

The as-of date minus the calendar date of Created, in whole days, for currently Approved, not Keyed Tickets. This is age since submission, not time spent waiting in the current state.

| Property | Value |
|---|---|
| Unit | days |
| Grain | Ticket |
| Statistic | median |
| Allowed dimensions | Approval Status; Keyed; Job Number; Job Name; Supervisor; Occupation |
| Null treatment | A Ticket with an unusable Created date is excluded and counted, never aged from zero. |
| Date basis | measured on Created to the analytical as-of date; Totals cover all dates unless a date range is set; a range always names its date basis. |
| Exclusions | Created is missing or not a date; Created falls after the as-of date: such a Ticket is left out and reported, never aged as zero |
| Lineage | One value per Approved, not Keyed Tickets Ticket, from its Created cell and the as-of date. |
| Percentage of | none |
| Requires columns | none |
| Buckets | `0`: 0 days; `1`: 1 day; `2`: 2 days; `3`: 3 days; `4-6`: 4–6 days; `7-13`: 7–13 days; `14-29`: 14–29 days; `30-or-more`: 30 days or more |
| Reads review links | no |

### `claimed_hours`: Claimed hours

Regular Hours + Overtime + Double Time as recorded, with no pay multipliers. Repeated claims are included as recorded.

| Property | Value |
|---|---|
| Unit | hours |
| Grain | Ticket |
| Statistic | sum |
| Allowed dimensions | Approval Status; Keyed; Job Number; Job Name; Supervisor; Occupation |
| Null treatment | A Ticket with a missing or invalid hour component is left out and reported in a coverage warning, never counted as zero. |
| Date basis | Totals cover all dates unless a date range is set; a range always names its date basis. |
| Exclusions | Tickets with a missing or invalid Regular Hours, Overtime or Double Time cell |
| Lineage | Each contributing Ticket's three hour cells. |
| Percentage of | none |
| Requires columns | none |
| Buckets | none |
| Reads review links | no |

### `reviewed_claimed_hours`: Analyst-reviewed claimed hours

Claimed hours (Regular Hours + Overtime + Double Time as recorded) for every Ticket under the filters except those a reviewer's kept/replaced link marks as replaced. Offered only beside the recorded figure, never instead of it.

| Property | Value |
|---|---|
| Unit | hours |
| Grain | Ticket |
| Statistic | sum |
| Allowed dimensions | Approval Status; Keyed; Job Number; Job Name; Supervisor; Occupation |
| Null treatment | A Ticket with a missing or invalid hour component is left out and reported in a coverage warning, never counted as zero. |
| Date basis | Totals cover all dates unless a date range is set; a range always names its date basis. |
| Exclusions | Tickets an explicit kept/replaced link marks as replaced; a Review Outcome or note alone never does; Tickets with a missing or invalid Regular Hours, Overtime or Double Time cell |
| Lineage | Each contributing Ticket's three hour cells, and the local review file's kept/replaced links. |
| Percentage of | none |
| Requires columns | none |
| Buckets | none |
| Reads review links | yes |

### `employee_label_count`: Employee labels

Distinct Employee labels after trimming, case-folding and collapsing whitespace. A count of labels, not of verified people; Aliases do not merge labels here.

| Property | Value |
|---|---|
| Unit | employee labels |
| Grain | Employee label |
| Statistic | distinct count |
| Allowed dimensions | Approval Status; Keyed; Job Number; Job Name; Supervisor; Occupation |
| Null treatment | A Ticket with no Employee text is left out and reported. |
| Date basis | Totals cover all dates unless a date range is set; a range always names its date basis. |
| Exclusions | Tickets with an empty Employee cell |
| Lineage | The Employee cell of every contributing Ticket. |
| Percentage of | none |
| Requires columns | none |
| Buckets | none |
| Reads review links | no |

### `submission_lag_days`: Submission lag

The calendar date of Created minus Date as recorded, in whole days, when both dates are usable.

| Property | Value |
|---|---|
| Unit | days |
| Grain | Ticket |
| Statistic | median |
| Allowed dimensions | Approval Status; Keyed; Job Number; Job Name; Supervisor; Occupation |
| Null treatment | A Ticket with an unusable Date or Created is excluded and counted. |
| Date basis | measured on Date as recorded to Created; Totals cover all dates unless a date range is set; a range always names its date basis. |
| Exclusions | Date or Created is missing or not a date; Date or Created outside the reporting window (an anomalous date, such as a work date years ahead) is a separate exception, shown as recorded and never corrected; Negative lag (work dated after its submission) is a separate exception, not discarded silently |
| Lineage | Each contributing Ticket's Date and Created cells. |
| Percentage of | none |
| Requires columns | none |
| Buckets | none |
| Reads review links | no |

### `observed_approval_interval_hours`: Observed approval interval

Date Approved minus Created, in hours, for Approved Tickets with valid nonnegative timestamps. Not a stage duration, and never applied to Rejected Tickets.

| Property | Value |
|---|---|
| Unit | hours |
| Grain | Ticket |
| Statistic | median |
| Allowed dimensions | Approval Status; Keyed; Job Number; Job Name; Supervisor; Occupation |
| Null treatment | An Approved Ticket with an unusable Created or Date Approved is excluded and counted. |
| Date basis | measured on Created to Date Approved; Totals cover all dates unless a date range is set; a range always names its date basis. |
| Exclusions | Tickets that are not Approved; Created or Date Approved is missing or not a date; Created or Date Approved outside the reporting window is a separate exception; Date Approved before Created is a separate exception |
| Lineage | Each contributing Ticket's Created and Date Approved cells. |
| Percentage of | none |
| Requires columns | Date Approved |
| Buckets | none |
| Reads review links | no |

### `known_base_value_bbd`: Known base-value components

Recorded Rate × claimed hours (Regular Hours + Overtime + Double Time, no multipliers) + Job Work Pay, rounded half-up to cents per Ticket and then summed, in BBD, over every Ticket under the filters, Rejected ones included. A partial valuation of submissions: the export holds no payment records, so it is not an amount disbursed, avoided or owed.

| Property | Value |
|---|---|
| Unit | BBD |
| Grain | Ticket |
| Statistic | sum |
| Allowed dimensions | Approval Status; Keyed; Job Number; Job Name; Supervisor; Occupation |
| Null treatment | Claimed labour on a Ticket with no usable Rate or hours is unpriced and disclosed, never valued at zero, and no Rate is taken from another Ticket; its Job Work Pay still counts. A Ticket with no known component is left out and reported. |
| Date basis | Totals cover all dates unless a date range is set; a range always names its date basis. |
| Exclusions | Tickets with neither priceable labour nor a usable Job Work Pay |
| Lineage | Each contributing Ticket's Rate, hour and Job Work Pay cells. |
| Percentage of | none |
| Requires columns | Rate |
| Buckets | none |
| Reads review links | no |

### `flagged_duplicate_base_value_bbd`: Base value of flagged duplicates

Recorded Rate × claimed hours (Regular Hours + Overtime + Double Time, no multipliers) + Job Work Pay, rounded half-up to cents per Ticket and then summed, in BBD, over the flagged duplicates (Approval Status Approved and Job Number 0), the Tickets flagged_duplicate_count counts. A partial valuation of submissions: the export holds no payment records, so it is not an amount disbursed, avoided or owed.

| Property | Value |
|---|---|
| Unit | BBD |
| Grain | Ticket |
| Statistic | sum |
| Allowed dimensions | Approval Status; Keyed; Job Number; Job Name; Supervisor; Occupation |
| Null treatment | Claimed labour on a Ticket with no usable Rate or hours is unpriced and disclosed, never valued at zero, and no Rate is taken from another Ticket; its Job Work Pay still counts. A Ticket with no known component is left out and reported. |
| Date basis | Totals cover all dates unless a date range is set; a range always names its date basis. |
| Exclusions | Tickets that are not flagged duplicates; Tickets with neither priceable labour nor a usable Job Work Pay |
| Lineage | Each contributing Ticket's Rate, hour and Job Work Pay cells. |
| Percentage of | none |
| Requires columns | Rate |
| Buckets | none |
| Reads review links | no |

### `unflagged_exact_repeat_extra_claim_bbd`: One extra claim per exact repeat, not flagged (hypothetical)

For each possible duplicate unflagged_exact_repeat_count counts (a Strict repeat group with no flagged duplicate and every Ticket Approved and Keyed), the base value of n - 1 of its n Tickets, in BBD: the group's per-Ticket base values (Rate × claimed hours + Job Work Pay, each rounded half-up to cents) summed, less the highest one, which is taken as the claim kept. Summed over those possible duplicates. A hypothetical count of redundant whole claims, valid only for strict groups and never for overlapping or partly matching tickets; it is not a confirmed excess, and the export holds no payment records.

| Property | Value |
|---|---|
| Unit | BBD |
| Grain | Possible duplicate |
| Statistic | sum |
| Allowed dimensions | none |
| Null treatment | A possible duplicate with a Ticket whose labour is unpriced (no usable Rate) is left out and reported, never valued at zero and never given another Ticket's Rate. |
| Date basis | Totals cover all dates unless a date range is set; a range always names its date basis. |
| Exclusions | Possible duplicates holding a flagged duplicate; Possible duplicates with any Ticket not Approved and Keyed; Possible duplicates with a Ticket whose labour is unpriced, which are reported; Tickets with a missing or invalid comparison field, which are reported |
| Lineage | Each possible duplicate lists its member Tickets by Excel row with each one's base value. |
| Percentage of | none |
| Requires columns | Rate |
| Buckets | none |
| Reads review links | no |

### `reviewed_known_base_value_bbd`: Analyst-reviewed known base-value components

Recorded Rate × claimed hours (Regular Hours + Overtime + Double Time, no multipliers) + Job Work Pay, rounded half-up to cents per Ticket and then summed, in BBD, over every Ticket under the filters except those a reviewer's kept/replaced link marks as replaced. A partial valuation of submissions: the export holds no payment records, so it is not an amount disbursed, avoided or owed.

| Property | Value |
|---|---|
| Unit | BBD |
| Grain | Ticket |
| Statistic | sum |
| Allowed dimensions | Approval Status; Keyed; Job Number; Job Name; Supervisor; Occupation |
| Null treatment | Claimed labour on a Ticket with no usable Rate or hours is unpriced and disclosed, never valued at zero, and no Rate is taken from another Ticket; its Job Work Pay still counts. A Ticket with no known component is left out and reported. |
| Date basis | Totals cover all dates unless a date range is set; a range always names its date basis. |
| Exclusions | Tickets an explicit kept/replaced link marks as replaced; a Review Outcome or note alone never does; Tickets with neither priceable labour nor a usable Job Work Pay |
| Lineage | Each contributing Ticket's Rate, hour and Job Work Pay cells. |
| Percentage of | none |
| Requires columns | Rate |
| Buckets | none |
| Reads review links | yes |

### `ambiguous_interval_ticket_count`: Ambiguous times

Tickets whose Time parse result holds at least one Ambiguous Interval: a work period with no AM/PM on one end or both. Its Plausible Reading is shown, labelled assumed, but it can never prove overlap or separation.

| Property | Value |
|---|---|
| Unit | tickets |
| Grain | Ticket |
| Statistic | count |
| Allowed dimensions | Approval Status; Keyed; Job Number; Job Name; Supervisor; Occupation |
| Null treatment | A Time cell that is blank, zero, a number or unreadable holds no period, so it is not counted here. |
| Date basis | Totals cover all dates unless a date range is set; a range always names its date basis. |
| Exclusions | Tickets whose every period is a Confident Interval, or whose Time holds no period |
| Lineage | Each Ticket's Time cell as the interval parser read it at import (parser version). |
| Percentage of | `ticket_count` |
| Requires columns | none |
| Buckets | none |
| Reads review links | no |

### `anomalous_date_count`: Dates outside the reporting window

Tickets with a Date as recorded, Created or Date Approved outside the reporting window, both ends inclusive. The window is visible and configurable and defaults to the years Created covers. Such dates are shown as recorded and never corrected, and no year is reassigned.

| Property | Value |
|---|---|
| Unit | tickets |
| Grain | Ticket |
| Statistic | count |
| Allowed dimensions | Approval Status; Keyed; Job Number; Job Name; Supervisor; Occupation |
| Null treatment | A missing or invalid date is an import issue, never an anomalous date. |
| Date basis | measured on Date as recorded, Created and Date Approved against the reporting window; Totals cover all dates unless a date range is set; a range always names its date basis. |
| Exclusions | Tickets whose usable dates all fall inside the window |
| Lineage | Each Ticket's Date, Created and Date Approved cells and the reporting window. |
| Percentage of | `ticket_count` |
| Requires columns | none |
| Buckets | none |
| Reads review links | no |

### `description_date_conflict_count`: Date conflicts in descriptions

Tickets whose Description of Job Work names an explicit date that differs from Date as recorded (the Description-date exception, pattern 6). Date is kept as recorded; the description never changes it, and the exception never links two tickets.

| Property | Value |
|---|---|
| Unit | tickets |
| Grain | Ticket |
| Statistic | count |
| Allowed dimensions | Approval Status; Keyed; Job Number; Job Name; Supervisor; Occupation |
| Null treatment | A description with no explicit date, a blank or non-text description, or an unusable Date is not counted; a reference with no year written is compared in the year of Date and flagged uncertain. |
| Date basis | Totals cover all dates unless a date range is set; a range always names its date basis. |
| Exclusions | Tickets whose description names no date, or only dates that agree with Date |
| Lineage | Each Ticket's Description of Job Work and Date cells, read at import (rules version). |
| Percentage of | `ticket_count` |
| Requires columns | Description of Job Work |
| Buckets | none |
| Reads review links | no |

### `missing_rate_count`: Missing rates

Tickets with no usable Rate: the Rate cell is blank or not a number. Their claimed labour cannot be priced and is never valued at zero or given another ticket's Rate.

| Property | Value |
|---|---|
| Unit | tickets |
| Grain | Ticket |
| Statistic | count |
| Allowed dimensions | Approval Status; Keyed; Job Number; Job Name; Supervisor; Occupation |
| Null treatment | Every Ticket without a usable Rate counts, whatever its hours. |
| Date basis | Totals cover all dates unless a date range is set; a range always names its date basis. |
| Exclusions | Tickets with a numeric Rate |
| Lineage | Each Ticket's Rate cell. |
| Percentage of | `ticket_count` |
| Requires columns | Rate |
| Buckets | none |
| Reads review links | no |

### `missing_required_field_count`: Missing required fields

Tickets with an empty required cell, as the import issues record it: a blank row, an empty required cell or a missing Ticket Number. The Ticket stays in the Snapshot and nothing is filled in.

| Property | Value |
|---|---|
| Unit | tickets |
| Grain | Ticket |
| Statistic | count |
| Allowed dimensions | Approval Status; Keyed; Job Number; Job Name; Supervisor; Occupation |
| Null treatment | A required cell holding an invalid value is a different import issue and is not counted here. |
| Date basis | Totals cover all dates unless a date range is set; a range always names its date basis. |
| Exclusions | Tickets whose required cells all hold a value |
| Lineage | The import issues of each Ticket (blank_row, missing_value, missing_business_id on a required column). |
| Percentage of | `ticket_count` |
| Requires columns | none |
| Buckets | none |
| Reads review links | no |

## Matching rules

Each rule proposes Candidates between two Tickets; evidence strength describes the matching evidence, never payment or intent.

| Rule | Pattern | Strength | Fields compared | Accepts a confirmed Alias | Reason shown |
|---|---|---|---|---|---|
| `strict_repeat` Strict repeat | Same claim appears twice | strong | Employee, Date, Job Number, Time, Regular Hours, Overtime, Double Time, Job Work Pay | no | Same claim submitted twice: employee, date, job, time and all four hour and pay amounts match. |
| `time_text_variant` Time-text variant | Same claim looks different as text | moderate | Employee, Date, Job Number, Time, Regular Hours, Overtime, Double Time, Job Work Pay | no | Same claim with the time written differently: employee, date, job and all four hour and pay amounts match, and the Time text differs only in spacing, case or punctuation, or reads as the same work periods. |
| `name_space_variant` Name-space variant | Same claim looks different as text | moderate | Employee, Date, Job Number, Time, Regular Hours, Overtime, Double Time, Job Work Pay | no | Same claim under two spellings of a name: the employee names are equal once spaces and case are ignored, and date, job, time and all four hour and pay amounts match. This proposes an Alias for a reviewer to confirm or reject; until then the two labels stay separate. |
| `work_period_conflict` Work-period conflict | Possible correction or resubmission | moderate | Employee, Date, Time | yes | Times overlap: work periods read without any assumption intersect on the same day. On its own an overlap is a conflicting work claim, not proof of a repeated whole ticket. |
| `ambiguous_period_comparison` Ambiguous-period comparison | Equal duration, separate periods | weak | Employee, Date, Job Number, Time, Regular Hours, Overtime, Double Time, Job Work Pay | no | Times need review: same job and all four hour and pay amounts, with times that lack AM/PM, so whether the work periods overlap cannot be established. |
| `flagged_duplicate_counterpart` Flagged-duplicate counterpart | Possible correction or resubmission | moderate | Employee, Date, Regular Hours, Overtime, Double Time, Job Work Pay, Time, Description of Job Work | yes | A flagged duplicate and a possible counterpart: one ticket was approved with Job Number 0, and the other is for the same employee and date with the same four hour and pay amounts, the same work periods, or (an uncertain counterpart) the same unresolved Time text and description. The current Job Number is not compared, and no counterpart is chosen as the original. |
| `repeated_component` Repeated component | Repeated payment component | weak | Employee, Date, Job Number, Job Work Pay | yes | Same task payment on both: equal positive Job Work Pay on the same day, on the same job or beside Job Number 0. A low-confidence component comparison: it compares one payment component, not the whole ticket. |
