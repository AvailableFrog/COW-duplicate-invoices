# Labour Ticket Analytics

The language for reviewing C.O. Williams labour-ticket exports: what the spreadsheet records, what matching rules find, and what a reviewer has judged. Screens use the plain duplicate language Oliver uses; the analytical terms below sit behind them.

## Language

### Source

**Ticket**:
One source record from a labour-ticket export, identified by its Snapshot and Excel row.
_Avoid_: row, record, invoice, claim

**Snapshot**:
One imported workbook, identified by its content fingerprint. A newer export is a new Snapshot, never extra Tickets in an old one.
_Avoid_: dataset, export, import, file

**Flagged Duplicate**:
A Ticket that staff flagged as a duplicate by approving it with Job Number 0. The flag is a fact about what staff did; whether the analysis agrees is shown beside it, never folded into the name.
_Avoid_: recorded marker, Job 0, detected duplicate, rejected duplicate

### Analysis

**Possible Duplicate**:
A set of Tickets the matching rules found that may repeat one another, opened and reviewed as one item. It may include a Flagged Duplicate and the ticket it appears to repeat.
_Avoid_: case, group, cluster, candidate group, suspected fraud

**Exact Repeat**:
A Possible Duplicate in which every claim field matches: employee, date, job, time, and all four hour and pay amounts.
_Avoid_: strict match, identical ticket, clear duplicate

**Candidate**:
One link between two Tickets inside a Possible Duplicate, carrying the rule that found it and the fields compared. An analytical term; screens show the reason in words instead.
_Avoid_: match, hit, flag

**Counterpart**:
A Ticket the Flagged-duplicate counterpart rule links to a Flagged Duplicate as a claim it may repeat: same employee (or confirmed Alias) and Date, with the same hours and pay, the same Confident Intervals, or (an uncertain counterpart) the same unresolved Time text and description. A Flagged Duplicate can have several, and none is chosen as the original; it stays unresolved until a reviewer settles one with Confirmed duplicate, Replacement ticket or a Replacement Link.
_Avoid_: original, retained claim (before review), match

**Confident Interval**:
A work period parsed from a Ticket's Time text with no assumption needed: explicit AM/PM or 24-hour form. Only Confident Intervals can establish overlap or separation.
_Avoid_: parsed time, valid time

**Ambiguous Interval**:
A work period whose Time text lacks a meridiem or is otherwise open to more than one reading. It carries a displayed Plausible Reading but can never prove overlap or separation.
_Avoid_: bad time, unparsed time, invalid time

**Plausible Reading**:
The single documented working-day interpretation shown for an Ambiguous Interval: a start between 5:00 and 11:59 is taken as AM and one from 12:00 to 4:59 as afternoon, and an end numerically below the start as PM. Always labelled as assumed.
_Avoid_: corrected time, fixed time, inferred time

**Annotation**:
A note attached to a Ticket by ticket number from the evidence report: its example letter, the consultant's review note, and the question for Oliver. Shown on evidence and never used to find Possible Duplicates.
_Avoid_: example, hardcoded case

### Review

**Review Outcome**:
A reviewer's judgement on a Possible Duplicate, kept in this app and never written back to the company's system. One of: Not reviewed, Confirmed duplicate, Not a duplicate, Replacement ticket, or Needs follow-up.
_Avoid_: verdict, status, disposition

**Confirmed Duplicate**:
A Review Outcome stating that the Tickets repeat the same claim. It says nothing about whether anyone was paid twice.
_Avoid_: confirmed repeat, proven duplicate, double payment

**Replacement Ticket**:
A Review Outcome stating that one Ticket corrects or supersedes another, with the kept and replaced Tickets linked.
_Avoid_: correction, resubmission, superseded claim

**Replacement Link**:
A reviewer's link from one replaced Ticket to one Ticket kept in its place; a replaced Ticket may have several kept Tickets, so no single survivor is forced. Only these links can take a Ticket out of an adjusted figure; a Review Outcome or note alone never does.
_Avoid_: survivor, original, winner, exclusion

**Alias**:
A reviewer-confirmed statement that two employee labels name one person, such as "Mario Collymore" and "Mariocollymore". Until confirmed it is only a suggestion. Once confirmed, the rules that accept an Alias compare both labels' tickets as one employee; the labels themselves are never merged or counted as one.
_Avoid_: merge, same person, fuzzy match, identity match

### Never claimed

**Paid twice**:
Not said anywhere. The export holds no payment records, so no screen may claim a payment was made, stopped, or made twice. Say Flagged duplicate, Exact repeat or Confirmed duplicate instead.
_Avoid_: double payment, loss, overpayment, fraud

**Missed duplicate**:
Not said for an unflagged Exact Repeat. Staff may have handled it somewhere the export cannot show; say "Exact repeat, not flagged".
_Avoid_: undetected duplicate, slipped through
