# Labour tickets: the questions that change the solution

C.O. Williams Construction Ltd. | Evidence report for the analytics PRD | Exported 14 October 2026

This is a readable export of the refactored discussion guide dated 12 October 2026, with the same six patterns and source examples.
The questions reflect the requester’s review; they do not establish duplicate intent, payment, or confirmed business rules.

## Source and reading conventions

Workbook: `Labour Tickets Export.xlsx`, sheet `Labour Tickets (1)`, 2,836 records and 22 columns.
Workbook SHA-256: `36378ee04717f2432b9ec7e3a999d484da7dd8de43ff51869ba88a68047004fb`.
Excel row numbers refer to the original worksheet; original zero-based dataframe index = Excel row minus 2.
Source cells below use JSON notation: quoted strings preserve spaces, `\n` denotes a line break, `null` is a blank, and `true`/`false` are booleans.
Date cells are represented as ISO strings; this changes their display, not their stored date/time value.
A **different** field differs across the compared rows; differences are not automatically evidence against duplication.

Oliver’s email says Approved tickets whose Job Number was changed to 0 were “more than likely a duplicate.”
That is a likely handling marker, not proof of a correct decision or a prevented payment.

Use these six patterns to establish what is being repeated, what staff already catch, and where a control would help.
They are hypotheses to test with Oliver, not six proven causes.

Oliver’s email identifies Approved / Job 0 as a likely duplicate marker.
It does not establish payment exclusion.
Approved/Keyed alone does not establish payment; Pending alone does not establish detection.
Different text does not establish intent.

## Start by watching the actual workflow

Ask Oliver to demonstrate one flagged ticket from submission through supervisor review, accounts and final disposition.
Which checks are automated, what does the red warning actually do, and where is a human decision recorded?

Use the cases below to clarify the consequential meanings of Keyed, Pending and Modified By.
Avoid guessing the detection rules from these labels alone.

Original A-N labels are retained. “My review notes” are condensed first-person paraphrases of your comments.
Each source dropdown preserves all 22 columns, including fields outside the discussion scope; amber highlights differing values.
Row references are Excel rows on Labour Tickets (1); dataframe index = row minus 2 for the original unsorted import.
Source date/time cells use ISO display; text is verbatim.

## Pattern 1: The same claim appears twice

These are the strongest apparent repeats without the described duplicate marker.
Start with Peter Holder.

1. Were these caught or missed? If caught, where is that decision recorded when both retain nonzero job numbers?
2. For Peter’s pair, show which ticket was retained and trace both through accounting and payment. Were both paid, or was one excluded elsewhere?

What the answer changes: Whether the gap is detection, recording the review decision, or preventing a second payment.

### C. Peter Holder: priority example

Same work on 28 September.
Only the ticket number, ID and creation/modification/approval timestamps differ.
Both are Approved and Keyed with job 41215.

<details>
<summary>My review notes (condensed paraphrase)</summary>

This looks like the strongest example of an undetected duplicate, possibly paid twice.
Keep it as the lead example, but ask Oliver whether it was handled somewhere we cannot see.

</details>

<details>
<summary>Exact source rows: 620 / 855</summary>

| Source field | Excel 620 / dataframe 618 | Excel 855 / dataframe 853 |
|---|---|---|
| Employee | `"Peter Holder"` | `"Peter Holder"` |
| Occupation | `"Labourer"` | `"Labourer"` |
| **Ticket Number (different)** | `"L225761"` | `"L225526"` |
| Job Name | `"Beachlands"` | `"Beachlands"` |
| Job Number | `41215` | `41215` |
| Date | `"2026-09-28 00:00:00"` | `"2026-09-28 00:00:00"` |
| Time | `"7:30 am to 4:30 pm"` | `"7:30 am to 4:30 pm"` |
| Regular Hours | `8` | `8` |
| Overtime | `0` | `0` |
| Double Time | `0` | `0` |
| Job Work Pay | `0` | `0` |
| Description of Job Work | `"None"` | `"None"` |
| Supervisor | `"Jamar O'Neal"` | `"Jamar O'Neal"` |
| Approval Status | `"Approved"` | `"Approved"` |
| **Modified (different)** | `"2026-10-05 07:48:00"` | `"2026-10-01 13:44:00"` |
| **Created (different)** | `"2026-10-02 18:56:00"` | `"2026-09-28 18:21:00"` |
| **ID (different)** | `224761` | `224526` |
| Email Address | `"Nardyspringer@gmail.com"` | `"Nardyspringer@gmail.com"` |
| Keyed | `true` | `true` |
| Rate | `14.53` | `14.53` |
| **Date Approved (different)** | `"2026-10-05 07:42:00"` | `"2026-09-29 09:36:00"` |
| Modified By | `"Tracy Whitehall"` | `"Tracy Whitehall"` |

</details>

### D. Latoya Small

Matching work fields on 18 September; both Approved and Keyed with nonzero jobs.

<details>
<summary>My review notes (condensed paraphrase)</summary>

The same concern as Peter: was this missed and paid twice, or dealt with outside the export?

</details>

<details>
<summary>Exact source rows: 974 / 1868</summary>

| Source field | Excel 974 / dataframe 972 | Excel 1868 / dataframe 1866 |
|---|---|---|
| Employee | `"Latoya Small"` | `"Latoya Small"` |
| Occupation | `"Checker"` | `"Checker"` |
| **Ticket Number (different)** | `"L225407"` | `"L224513"` |
| Job Name | `"Shop hill"` | `"Shop hill"` |
| Job Number | `40972` | `40972` |
| Date | `"2026-09-18 00:00:00"` | `"2026-09-18 00:00:00"` |
| Time | `"7:30am - 4:30pm"` | `"7:30am - 4:30pm"` |
| Regular Hours | `8` | `8` |
| Overtime | `0` | `0` |
| Double Time | `0` | `0` |
| Job Work Pay | `0` | `0` |
| Description of Job Work | `0` | `0` |
| Supervisor | `"Ammir Cobham"` | `"Ammir Cobham"` |
| Approval Status | `"Approved"` | `"Approved"` |
| **Modified (different)** | `"2026-09-28 08:33:00"` | `"2026-09-25 08:37:00"` |
| **Created (different)** | `"2026-09-28 07:13:00"` | `"2026-09-20 06:34:00"` |
| **ID (different)** | `224407` | `223513` |
| Email Address | `"Latoyasmall246@gmail.com"` | `"Latoyasmall246@gmail.com"` |
| Keyed | `true` | `true` |
| Rate | `19.08` | `19.08` |
| **Date Approved (different)** | `"2026-09-28 08:06:00"` | `"2026-09-21 08:07:00"` |
| Modified By | `"Tracy Whitehall"` | `"Tracy Whitehall"` |

</details>

### E. Samantha Drakes

Another matching Approved/Keyed pair for 18 September.
Useful corroborating example.

<details>
<summary>Exact source rows: 1309 / 1656</summary>

| Source field | Excel 1309 / dataframe 1307 | Excel 1656 / dataframe 1654 |
|---|---|---|
| Employee | `"Samantha Drakes"` | `"Samantha Drakes"` |
| Occupation | `"Checker"` | `"Checker"` |
| **Ticket Number (different)** | `"L225072"` | `"L224725"` |
| Job Name | `"Massy Worthing"` | `"Massy Worthing"` |
| Job Number | `41149` | `41149` |
| Date | `"2026-09-18 00:00:00"` | `"2026-09-18 00:00:00"` |
| Time | `"7.30am to 4.30pm"` | `"7.30am to 4.30pm"` |
| Regular Hours | `8` | `8` |
| Overtime | `1` | `1` |
| Double Time | `0` | `0` |
| Job Work Pay | `0` | `0` |
| Description of Job Work | `0` | `0` |
| Supervisor | `"Raneil Smith"` | `"Raneil Smith"` |
| Approval Status | `"Approved"` | `"Approved"` |
| **Modified (different)** | `"2026-09-28 08:05:00"` | `"2026-09-24 15:45:00"` |
| **Created (different)** | `"2026-09-25 08:58:00"` | `"2026-09-21 07:22:00"` |
| **ID (different)** | `224072` | `223725` |
| Email Address | `"Kaleeyhia@gmail.com"` | `"Kaleeyhia@gmail.com"` |
| Keyed | `true` | `true` |
| Rate | `19.08` | `19.08` |
| **Date Approved (different)** | `"2026-09-28 07:01:00"` | `"2026-09-22 07:56:00"` |
| Modified By | `"Tracy Whitehall"` | `"Tracy Whitehall"` |

</details>

### F. Mario Collymore: 10 September

Matching work fields and Approved/Keyed status; description punctuation differs.
This is a separate case from H’s name variation on 23 September.

<details>
<summary>Exact source rows: 2206 / 2351</summary>

| Source field | Excel 2206 / dataframe 2204 | Excel 2351 / dataframe 2349 |
|---|---|---|
| Employee | `"Mario Collymore"` | `"Mario Collymore"` |
| Occupation | `"Labourer"` | `"Labourer"` |
| **Ticket Number (different)** | `"L224175"` | `"L224030"` |
| Job Name | `"Sandals"` | `"Sandals"` |
| Job Number | `41122` | `41122` |
| Date | `"2026-09-10 00:00:00"` | `"2026-09-10 00:00:00"` |
| Time | `"7:30am-4:30pm"` | `"7:30am-4:30pm"` |
| Regular Hours | `8` | `8` |
| Overtime | `1` | `1` |
| Double Time | `0` | `0` |
| Job Work Pay | `0` | `0` |
| **Description of Job Work (different)** | `"………"` | `"……"` |
| Supervisor | `"Joshua Ruck"` | `"Joshua Ruck"` |
| Approval Status | `"Approved"` | `"Approved"` |
| **Modified (different)** | `"2026-09-14 14:51:00"` | `"2026-09-14 13:09:00"` |
| **Created (different)** | `"2026-09-14 13:51:00"` | `"2026-09-13 18:30:00"` |
| **ID (different)** | `223175` | `223030` |
| **Email Address (different)** | `"Mariocollymore8@gmail.com"` | `"Mariocollymore8@gamil.com"` |
| Keyed | `true` | `true` |
| Rate | `14.53` | `14.53` |
| **Date Approved (different)** | `"2026-09-14 14:10:00"` | `"2026-09-14 12:59:00"` |
| Modified By | `"Mavis Lowe"` | `"Mavis Lowe"` |

</details>

## Pattern 2: The same claim looks different as text

Small time or name variations can affect matching.
Pending status does not reveal whether a reviewer has already spotted the repeat.

1. Did the warning catch G and H despite the spacing differences, and were these tickets awaiting review or deliberately held?
2. What identifies the employee and work period in the actual check? Are names/times controlled fields, and does Modified By reveal a user edit, approval or automated update?

What the answer changes: Whether to normalize inputs, fix employee identification, or record warning and review outcomes more clearly.

### G. Kerriann white: spacing in time

Same job and work fields; time spacing differs.
Both tickets are Pending and not Keyed.

<details>
<summary>My review notes (condensed paraphrase)</summary>

Show Oliver this one explicitly.
Why are there two submissions with slightly different spacing?
Does the red warning merely alert someone, or does it record or block anything?
I cannot tell whether Pending means waiting or already caught.

</details>

<details>
<summary>Exact source rows: 82 / 103</summary>

| Source field | Excel 82 / dataframe 80 | Excel 103 / dataframe 101 |
|---|---|---|
| Employee | `"Kerriann white"` | `"Kerriann white"` |
| Occupation | `"Checker"` | `"Checker"` |
| **Ticket Number (different)** | `"L226299"` | `"L226278"` |
| Job Name | `"Melvin’s hill"` | `"Melvin’s hill"` |
| Job Number | `41174` | `41174` |
| Date | `"2026-10-06 00:00:00"` | `"2026-10-06 00:00:00"` |
| **Time (different)** | `"730am 430 pm"` | `"730 am 430 pm"` |
| Regular Hours | `8` | `8` |
| Overtime | `1` | `1` |
| Double Time | `0` | `0` |
| Job Work Pay | `0` | `0` |
| Description of Job Work | `0` | `0` |
| Supervisor | `"Joshua Ruck"` | `"Joshua Ruck"` |
| Approval Status | `"Pending"` | `"Pending"` |
| **Modified (different)** | `"2026-10-07 09:02:00"` | `"2026-10-06 21:01:00"` |
| **Created (different)** | `"2026-10-07 09:02:00"` | `"2026-10-06 21:01:00"` |
| **ID (different)** | `225299` | `225278` |
| **Email Address (different)** | `"Kerriannwhite95@gmail.com"` | `"Kerriannwhite95’gmail.com"` |
| Keyed | `false` | `false` |
| Rate | `null` | `null` |
| Date Approved | `null` | `null` |
| Modified By | `"Oliver Williams"` | `"Oliver Williams"` |

</details>

### H. Mario Collymore: name variation

Mario Collymore versus Mariocollymore for 23 September.
Modified By is Tracy Whitehall versus Oliver Williams.
The Pending ticket was created on 27 September, before the Approved/Keyed ticket on 29 September.

<details>
<summary>My review notes (condensed paraphrase)</summary>

Why did the name change, and what do the two Modified By names mean?
My tentative guess was that one ticket had not been reviewed, but it could be a replacement or a held duplicate.
The spelling does not establish intent.

</details>

<details>
<summary>Exact source rows: 829 / 1072</summary>

| Source field | Excel 829 / dataframe 827 | Excel 1072 / dataframe 1070 |
|---|---|---|
| **Employee (different)** | `"Mario Collymore"` | `"Mariocollymore"` |
| Occupation | `"Labourer"` | `"Labourer"` |
| **Ticket Number (different)** | `"L225552"` | `"L225309"` |
| **Job Name (different)** | `"Sandals"` | `"Sandals "` |
| Job Number | `41122` | `41122` |
| Date | `"2026-09-23 00:00:00"` | `"2026-09-23 00:00:00"` |
| Time | `"7:30am-4:30pm"` | `"7:30am-4:30pm"` |
| Regular Hours | `8` | `8` |
| Overtime | `1` | `1` |
| Double Time | `0` | `0` |
| Job Work Pay | `0` | `0` |
| Description of Job Work | `"…….."` | `"…….."` |
| **Supervisor (different)** | `"Dane Skeete"` | `"Craig Baxter"` |
| **Approval Status (different)** | `"Approved"` | `"Pending"` |
| **Modified (different)** | `"2026-09-29 13:59:00"` | `"2026-09-27 19:41:00"` |
| **Created (different)** | `"2026-09-29 09:31:00"` | `"2026-09-27 19:41:00"` |
| **ID (different)** | `224552` | `224309` |
| Email Address | `"Mariocollymore8@gmail.com"` | `"Mariocollymore8@gmail.com"` |
| **Keyed (different)** | `true` | `false` |
| **Rate (different)** | `14.53` | `null` |
| **Date Approved (different)** | `"2026-09-29 13:28:00"` | `null` |
| **Modified By (different)** | `"Tracy Whitehall"` | `"Oliver Williams"` |

</details>

## Pattern 3: A new ticket may replace an earlier one

Changed fields may reflect a correction or resubmission.
Overlapping claims cannot be counted as independent worked shifts merely because the details differ.

1. Using J, can an employee correct, cancel or resubmit to another supervisor, and can both reviewers see the earlier claim? Why did the time and supervisor change?
2. Using I, what evidence linked the records despite different occupation, site and description? Is the valid ticket explicitly linked to the superseded one?

What the answer changes: Whether the main need is overlap detection or a correction workflow that leaves only one valid claim.

### J. Orlando Richards: time and supervisor change

Same job, overlapping periods and compatible descriptions; different supervisors.
Both are Pending/not-Keyed, with Modified By Oliver Williams.
The later ticket changes the start time.

<details>
<summary>My review notes (condensed paraphrase)</summary>

These cannot be separate additive shifts as written.
Is this a legitimate correction or another attempt to get an outstanding claim approved?
I need the workflow and the time-comparison logic before judging intent.

</details>

<details>
<summary>Exact source rows: 61 / 105</summary>

| Source field | Excel 61 / dataframe 59 | Excel 105 / dataframe 103 |
|---|---|---|
| Employee | `"Orlando Richards"` | `"Orlando Richards"` |
| Occupation | `"Labourer"` | `"Labourer"` |
| **Ticket Number (different)** | `"L226320"` | `"L226276"` |
| Job Name | `"Chancery Lane "` | `"Chancery Lane "` |
| Job Number | `41202` | `41202` |
| Date | `"2026-10-06 00:00:00"` | `"2026-10-06 00:00:00"` |
| **Time (different)** | `"12:30-4:30"` | `"11:30-4:30"` |
| Regular Hours | `4` | `4` |
| Overtime | `0` | `0` |
| Double Time | `0` | `0` |
| Job Work Pay | `0` | `0` |
| **Description of Job Work (different)** | `"Working along with the excavator man digging to find the pipes so he can’t burst them  "` | `"I working along the road with the excavator man"` |
| **Supervisor (different)** | `"Herbert Hackett"` | `"Adrian Mayers"` |
| Approval Status | `"Pending"` | `"Pending"` |
| **Modified (different)** | `"2026-10-07 18:59:00"` | `"2026-10-06 20:05:00"` |
| **Created (different)** | `"2026-10-07 18:59:00"` | `"2026-10-06 20:05:00"` |
| **ID (different)** | `225320` | `225276` |
| Email Address | `"orlandorichards912@gmail.com"` | `"orlandorichards912@gmail.com"` |
| Keyed | `false` | `false` |
| Rate | `null` | `null` |
| Date Approved | `null` | `null` |
| Modified By | `"Oliver Williams"` | `"Oliver Williams"` |

</details>

### I. Damar Graham: occupation and site change

An Approved/Job 0 record differs from the apparent original in occupation, site and description.
Rejected row 999 connects the road-preparation and plainer wording.

<details>
<summary>My review notes (condensed paraphrase)</summary>

Why do the occupation, site and work description vary so much if staff considered this the same claim?
What does Rectro ticket mean, and which original did they identify?

</details>

<details>
<summary>Exact source rows: 318 / 1545 / 999</summary>

| Source field | Excel 318 / dataframe 316 | Excel 1545 / dataframe 1543 | Excel 999 / dataframe 997 |
|---|---|---|---|
| Employee | `"Damar Graham"` | `"Damar Graham"` | `"Damar Graham"` |
| **Occupation (different)** | `"Labourer"` | `"Charge Hand"` | `"Charge Hand"` |
| **Ticket Number (different)** | `"L226063"` | `"L224836"` | `"L225382"` |
| **Job Name (different)** | `"Date tree hill"` | `"Boscoble"` | `"Date tree hill"` |
| **Job Number (different)** | `0` | `41279` | `41279` |
| Date | `"2026-09-14 00:00:00"` | `"2026-09-14 00:00:00"` | `"2026-09-14 00:00:00"` |
| Time | `"7:30am-4:30pm"` | `"7:30am-4:30pm"` | `"7:30am-4:30pm"` |
| Regular Hours | `8` | `8` | `8` |
| Overtime | `1` | `1` | `1` |
| Double Time | `0` | `0` | `0` |
| Job Work Pay | `0` | `0` | `0` |
| **Description of Job Work (different)** | `"Preparing road \nRectro ticket"` | `"Working with plainer"` | `"Preparing road worked with plainer \nRectro ticket"` |
| Supervisor | `"Troy Small"` | `"Troy Small"` | `"Troy Small"` |
| **Approval Status (different)** | `"Approved"` | `"Approved"` | `"Rejected"` |
| **Modified (different)** | `"2026-10-06 14:30:00"` | `"2026-09-22 07:35:00"` | `"2026-09-29 08:34:00"` |
| **Created (different)** | `"2026-10-05 06:36:00"` | `"2026-09-22 06:38:00"` | `"2026-09-28 06:25:00"` |
| **ID (different)** | `225063` | `223836` | `224382` |
| **Email Address (different)** | `"Damargraham92@gmail.com"` | `"Damargraham92@gnail.com"` | `"Damargraham92@gmail.com"` |
| **Keyed (different)** | `true` | `true` | `false` |
| **Rate (different)** | `14.53` | `19.47` | `19.47` |
| **Date Approved (different)** | `"2026-10-05 08:21:00"` | `"2026-09-22 07:29:00"` | `"2026-09-29 08:34:00"` |
| **Modified By (different)** | `"Mavis Lowe"` | `"Tracy Whitehall"` | `"Oliver Williams"` |

</details>

### K. Errol Thornhill: changed claim fields

Same date, time and description, with changed hour fields.
One record is Job 0; both are Approved and Keyed.
Retained as another replacement example, without investigating pay-rate calculations.

<details>
<summary>My review notes (condensed paraphrase)</summary>

The marker suggests one was treated as duplicate and the other retained.
The useful question is how they established that relationship when the claim fields changed.

</details>

<details>
<summary>Exact source rows: 2188 / 2187</summary>

| Source field | Excel 2188 / dataframe 2186 | Excel 2187 / dataframe 2185 |
|---|---|---|
| Employee | `"Errol Thornhill"` | `"Errol Thornhill"` |
| Occupation | `"Carpenter A Class"` | `"Carpenter A Class"` |
| **Ticket Number (different)** | `"L224193"` | `"L224194"` |
| Job Name | `"Wesley hall"` | `"Wesley hall"` |
| **Job Number (different)** | `0` | `41297` |
| Date | `"2026-09-12 00:00:00"` | `"2026-09-12 00:00:00"` |
| Time | `"7:30-4:30"` | `"7:30-4:30"` |
| **Regular Hours (different)** | `8` | `0` |
| Overtime | `0` | `0` |
| **Double Time (different)** | `0` | `9` |
| Job Work Pay | `0` | `0` |
| Description of Job Work | `"Boxing"` | `"Boxing"` |
| Supervisor | `"Bradford Goodluck"` | `"Bradford Goodluck"` |
| Approval Status | `"Approved"` | `"Approved"` |
| **Modified (different)** | `"2026-09-21 12:00:00"` | `"2026-09-21 12:06:00"` |
| **Created (different)** | `"2026-09-14 17:57:00"` | `"2026-09-14 17:59:00"` |
| **ID (different)** | `223193` | `223194` |
| Email Address | `"errolthornhill40@gmail.com"` | `"errolthornhill40@gmail.com"` |
| Keyed | `true` | `true` |
| Rate | `19.47` | `19.47` |
| **Date Approved (different)** | `"2026-09-20 20:52:00"` | `"2026-09-20 20:53:00"` |
| Modified By | `"Tracy Whitehall"` | `"Tracy Whitehall"` |

</details>

## Pattern 4: Equal duration, separate work periods

These records are consistent with separate work being accepted.
They are comparisons for testing a rule, not evidence that C.O.
Williams falsely marked them as duplicates.

1. Using B’s two visits to the same job, show how the current check distinguishes separate periods from repeated work. Does it use time, or does a person decide?
2. What is the intended unit of submission: one employee-day, one job or one period? How should split work be recorded while preserving job allocations?

What the answer changes: Whether the fix is time parsing, a clearer daily form, or both.
Equal hours alone cannot determine duplication.

### B. Patrick Gittens: same job, separate visits

Lears, job 20105, on 7 October; two one-hour periods.
Both Approved with nonzero jobs, but not Keyed.
This is closer to the original concern than A.

<details>
<summary>My review notes (condensed paraphrase)</summary>

Both seem to have been accepted.
Was that because someone checked the times?
Also, what does Keyed False mean after approval?

</details>

<details>
<summary>Exact source rows: 33 / 79</summary>

| Source field | Excel 33 / dataframe 31 | Excel 79 / dataframe 77 |
|---|---|---|
| Employee | `"Patrick Gittens"` | `"Patrick Gittens"` |
| Occupation | `"Chainman"` | `"Chainman"` |
| **Ticket Number (different)** | `"L226348"` | `"L226302"` |
| Job Name | `"Lears"` | `"Lears"` |
| Job Number | `20105` | `20105` |
| Date | `"2026-10-07 00:00:00"` | `"2026-10-07 00:00:00"` |
| **Time (different)** | `"1030-1130"` | `"730-830"` |
| Regular Hours | `1` | `1` |
| Overtime | `0` | `0` |
| Double Time | `0` | `0` |
| Job Work Pay | `0` | `0` |
| Description of Job Work | `0` | `0` |
| Supervisor | `"Scott Fenty"` | `"Scott Fenty"` |
| Approval Status | `"Approved"` | `"Approved"` |
| Modified | `"2026-10-08 07:36:00"` | `"2026-10-08 07:36:00"` |
| **Created (different)** | `"2026-10-08 07:30:00"` | `"2026-10-07 10:39:00"` |
| **ID (different)** | `225348` | `225302` |
| Email Address | `"patrickgittens52@gmail.com"` | `"patrickgittens52@gmail.com"` |
| Keyed | `false` | `false` |
| Rate | `17.05` | `17.05` |
| Date Approved | `"2026-10-08 07:36:00"` | `"2026-10-08 07:36:00"` |
| Modified By | `"Oliver Williams"` | `"Oliver Williams"` |

</details>

### A. Romarian Alleyne: different jobs

Separate morning/afternoon periods and different job identifiers.
The job identifiers may distinguish these without any time parsing.

<details>
<summary>My review notes (condensed paraphrase)</summary>

This does not show a company false positive.
My concern was separate periods that otherwise look like the same job, so we need the real automated and human rules.

</details>

<details>
<summary>Exact source rows: 591 / 593</summary>

| Source field | Excel 591 / dataframe 589 | Excel 593 / dataframe 591 |
|---|---|---|
| Employee | `"Romarian Alleyne"` | `"Romarian Alleyne"` |
| Occupation | `"Labourer"` | `"Labourer"` |
| **Ticket Number (different)** | `"L225790"` | `"L225788"` |
| **Job Name (different)** | `"Beachlands"` | `"HR Meeting"` |
| **Job Number (different)** | `41215` | `20125` |
| Date | `"2026-10-02 00:00:00"` | `"2026-10-02 00:00:00"` |
| **Time (different)** | `"12:30 PM - 4:30 PM"` | `"7:30 AM - 11:30 AM"` |
| Regular Hours | `4` | `4` |
| Overtime | `0` | `0` |
| Double Time | `0` | `0` |
| Job Work Pay | `0` | `0` |
| Description of Job Work | `"."` | `"."` |
| Supervisor | `"Gregory Mayers"` | `"Gregory Mayers"` |
| Approval Status | `"Approved"` | `"Approved"` |
| **Modified (different)** | `"2026-10-06 14:58:00"` | `"2026-10-06 14:54:00"` |
| **Created (different)** | `"2026-10-03 08:28:00"` | `"2026-10-03 08:26:00"` |
| **ID (different)** | `224790` | `224788` |
| Email Address | `"romarian.alleyne@gmail.com"` | `"romarian.alleyne@gmail.com"` |
| Keyed | `false` | `false` |
| Rate | `14.53` | `14.53` |
| **Date Approved (different)** | `"2026-10-06 14:58:00"` | `"2026-10-06 14:54:00"` |
| Modified By | `"Oliver Williams"` | `"Oliver Williams"` |

</details>

### L. Weston Holder: multiple periods in one ticket

Separate periods; both Approved/Keyed with nonzero jobs.
One Time cell contains two periods separated by an underscore.

<details>
<summary>My review notes (condensed paraphrase)</summary>

This appears to have been accepted correctly.
Low priority: can their time handling recognize both periods separated by the underscore?

</details>

<details>
<summary>Exact source rows: 2151 / 2152</summary>

| Source field | Excel 2151 / dataframe 2149 | Excel 2152 / dataframe 2150 |
|---|---|---|
| Employee | `"Weston Holder"` | `"Weston Holder"` |
| Occupation | `"Chainman"` | `"Chainman"` |
| **Ticket Number (different)** | `"L224230"` | `"L224229"` |
| **Job Name (different)** | `"Pendry hotel"` | `"Lears yard"` |
| **Job Number (different)** | `41027` | `20105` |
| Date | `"2026-09-11 00:00:00"` | `"2026-09-11 00:00:00"` |
| **Time (different)** | `"1030am 230pm"` | `"730am 1030am _ 230pm 430pm"` |
| **Regular Hours (different)** | `3` | `5` |
| **Overtime (different)** | `1` | `0` |
| Double Time | `0` | `0` |
| Job Work Pay | `0` | `0` |
| Description of Job Work | `0` | `0` |
| Supervisor | `"Ryan King"` | `"Ryan King"` |
| Approval Status | `"Approved"` | `"Approved"` |
| **Modified (different)** | `"2026-09-21 15:31:00"` | `"2026-09-20 08:27:00"` |
| **Created (different)** | `"2026-09-15 16:40:00"` | `"2026-09-15 16:36:00"` |
| **ID (different)** | `223230` | `223229` |
| Email Address | `"holderweston23gmail.com"` | `"holderweston23gmail.com"` |
| Keyed | `true` | `true` |
| Rate | `17.05` | `17.05` |
| Date Approved | `"2026-09-20 05:18:00"` | `"2026-09-20 05:18:00"` |
| **Modified By (different)** | `"Tracy Whitehall"` | `"Erin Marshall"` |

</details>

## Pattern 5: A payment component may be repeated

Matching an allowance or task payment is different from matching the whole labour ticket.
A duplicate marker must still leave the valid entitlement identifiable.

1. Why are both M records Job 0? Which ticket or accounting entry retained any valid payment, and could either claim have been wrongly excluded?
2. Do the two Job Work Pay amounts represent the same entitlement? How are those payments linked to labour claims or replacements?

What the answer changes: Whether checks need to compare payment components and replacement links rather than reject whole tickets.

### M. Weston Holder: both records marked Job 0

Both carry Job Work Pay 50 and are Approved/Keyed with Job 0.
The ticket containing hours was created on 15 September; the no-hours ticket followed on 21 September.

<details>
<summary>My review notes (condensed paraphrase)</summary>

Could one be an incomplete claim and the other a correction?
Why were both marked, and where is the valid claim?
My original idea that hours were added later is contradicted by the creation dates.

</details>

<details>
<summary>Exact source rows: 1575 / 2149</summary>

| Source field | Excel 1575 / dataframe 1573 | Excel 2149 / dataframe 2147 |
|---|---|---|
| Employee | `"Weston Holder"` | `"Weston Holder"` |
| Occupation | `"Chainman"` | `"Chainman"` |
| **Ticket Number (different)** | `"L224806"` | `"L224232"` |
| Job Name | `"Pendry hotel"` | `"Pendry hotel"` |
| Job Number | `0` | `0` |
| Date | `"2026-09-11 00:00:00"` | `"2026-09-11 00:00:00"` |
| **Time (different)** | `0` | `"1030am 1230pm"` |
| **Regular Hours (different)** | `0` | `2` |
| Overtime | `0` | `0` |
| Double Time | `0` | `0` |
| Job Work Pay | `50` | `50` |
| **Description of Job Work (different)** | `"$50.00  for topographical survey in sea"` | `"Working in water."` |
| Supervisor | `"Ryan King"` | `"Ryan King"` |
| Approval Status | `"Approved"` | `"Approved"` |
| **Modified (different)** | `"2026-09-29 13:41:00"` | `"2026-09-21 15:30:00"` |
| **Created (different)** | `"2026-09-21 17:15:00"` | `"2026-09-15 17:01:00"` |
| **ID (different)** | `223806` | `223232` |
| Email Address | `"holderweston"` | `"holderweston"` |
| Keyed | `true` | `true` |
| Rate | `17.05` | `17.05` |
| **Date Approved (different)** | `"2026-09-25 15:26:00"` | `"2026-09-20 05:17:00"` |
| Modified By | `"Tracy Whitehall"` | `"Tracy Whitehall"` |

</details>

## Pattern 6: The work date is buried in the description

Two tickets can share the Date field while describing different service dates.
The export does not establish whether these were previously uninvoiced tasks.

1. What does Date represent here, and how are the actual service date and any earlier claim/payment checked?
2. Is the check currently manual because service dates are free text, or is there structured information elsewhere?

What the answer changes: Whether to capture service dates explicitly and check claim history; free text alone does not make this inherently unautomatable.

### N. Toyna Elcock: retrospective task claims

Both Date cells say 11 September and Job Work Pay is 20, but descriptions name the 9th and the 7th.
Time and labour hours are zero.

<details>
<summary>My review notes (condensed paraphrase)</summary>

This looks like catch-up invoicing for missed dates.
How is it reviewed, and is any logic enforced?
I wondered whether it needs manual handling; ask what information would allow a reliable check.

</details>

<details>
<summary>Exact source rows: 1727 / 1728</summary>

| Source field | Excel 1727 / dataframe 1725 | Excel 1728 / dataframe 1726 |
|---|---|---|
| Employee | `"Toyna Elcock"` | `"Toyna Elcock"` |
| Occupation | `"Checker"` | `"Checker"` |
| **Ticket Number (different)** | `"L224654"` | `"L224653"` |
| **Job Name (different)** | `"Ncc boardwalk Hastings"` | `"Barry Wash"` |
| **Job Number (different)** | `41303` | `41243` |
| Date | `"2026-09-11 00:00:00"` | `"2026-09-11 00:00:00"` |
| Time | `0` | `0` |
| Regular Hours | `0` | `0` |
| Overtime | `0` | `0` |
| Double Time | `0` | `0` |
| Job Work Pay | `20` | `20` |
| **Description of Job Work (different)** | `"Ticket for the 9th September 2026"` | `"Ticket for the 7th of September"` |
| Supervisor | `"Jamar O'Neal"` | `"Jamar O'Neal"` |
| Approval Status | `"Approved"` | `"Approved"` |
| Modified | `"2026-09-22 15:40:00"` | `"2026-09-22 15:40:00"` |
| **Created (different)** | `"2026-09-20 21:47:00"` | `"2026-09-20 21:46:00"` |
| **ID (different)** | `223654` | `223653` |
| Email Address | `"Tonyaelcock1225@gmail.com"` | `"Tonyaelcock1225@gmail.com"` |
| Keyed | `true` | `true` |
| Rate | `19.08` | `19.08` |
| Date Approved | `"2026-09-21 05:23:00"` | `"2026-09-21 05:23:00"` |
| Modified By | `"Tracy Whitehall"` | `"Tracy Whitehall"` |

</details>

## Cost context only

| Existing base estimate | BBD |
|---|---:|
| Known-value subtotal of all tickets, including rejected submissions | 341,477.32 |
| 28 Approved / Job 0 records: potential avoided value | 3,399.71 |
| One redundant claim per strong unmarked pair C-F: potential excess value | 571.37 |

All hour categories valued at the recorded regular rate, plus Job Work Pay.
No premium-rate analysis.
Labour on 122 Pending tickets remains unpriced.
These estimates are not verified savings or payments; confirm disposition before using them as business impact.

Source: Labour Tickets Export.xlsx, 2,836 records, and the requester’s review comments.
Source tables were checked against the workbook.
No company false-positive decision is established by A/B/L/N; M’s treatment remains a question.
The meeting should leave us with the valid claim, the recorded decision and the necessary control for each pattern.
