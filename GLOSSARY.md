# Labour Ticket Analytics

The language for reviewing C.O. Williams labour-ticket exports: what the spreadsheet records, what matching rules propose, and what a reviewer has judged. The three are kept apart on purpose.

## Language

### Source

**Ticket**:
One source record from a labour-ticket export, identified by its Snapshot and Excel row.
_Avoid_: row, record, invoice, claim

**Snapshot**:
One imported workbook, identified by its content fingerprint. A newer export is a new Snapshot, never extra Tickets in an old one.
_Avoid_: dataset, export, import, file

**Recorded Marker**:
A Ticket whose Approval Status is Approved and whose Job Number is 0. Oliver described these as "more than likely a duplicate"; the term asserts nothing about detection or payment.
_Avoid_: detected duplicate, caught duplicate, marked duplicate, Job 0

### Analysis

**Candidate**:
A relationship between two Tickets that a matching rule proposed, carrying the rule, the fields compared, and the strength of the matching evidence. Strength says nothing about payment or intent.
_Avoid_: duplicate, match, hit, flag

**Case**:
The connected set of Candidates within one employee-and-date context. The unit a reviewer opens; membership does not mean every member repeats every other.
_Avoid_: group, pair, cluster, incident

**Confident Interval**:
A work period parsed from a Ticket's Time text with no assumption needed: explicit AM/PM or 24-hour form. Only Confident Intervals can establish overlap or separation.
_Avoid_: parsed time, valid time

**Ambiguous Interval**:
A work period whose Time text lacks a meridiem or is otherwise open to more than one reading. It carries a displayed Plausible Reading but can never prove overlap or separation.
_Avoid_: bad time, unparsed time, invalid time

**Plausible Reading**:
The single documented working-day interpretation shown for an Ambiguous Interval: a start between 5:00 and 11:59 is taken as AM, and an end numerically below the start as PM. Always labelled as assumed.
_Avoid_: corrected time, fixed time, inferred time

**Annotation**:
A note attached to a Ticket by ticket number from the evidence report: its example letter, the consultant's review note, and the question for Oliver. Annotations are displayed on evidence and never used by matching rules.
_Avoid_: example, hardcoded case

### Review

**Review Outcome**:
A reviewer's local judgement on a Case or Candidate: unreviewed, confirmed repeat, legitimate separate work, correction or replacement, or unresolved. Recorded outside the source and never written back.
_Avoid_: decision, verdict, status, disposition

**Alias**:
A reviewer-confirmed statement that two employee labels name one person. Until confirmed, a proposed alias is only a Candidate.
_Avoid_: merge, same person, fuzzy match, identity match

### Banned

**duplicate**:
Not used in code, UI, tickets, or docs except when quoting Oliver's email. Say Recorded Marker, Candidate, Case, or confirmed repeat instead.
