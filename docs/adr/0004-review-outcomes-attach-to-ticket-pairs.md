---
status: accepted
---

# Review Outcomes attach to ticket pairs, never to Cases

A Case is recomposed every time the matching rules run, so a Review Outcome keyed by Case ID would be orphaned by any rule change. We decided that an outcome attaches to the order-independent pair of Tickets behind a Candidate, and that a retained/replaced link attaches to individual Tickets; a Case only displays the outcomes of its member pairs. The alternative, snapshotting Case membership at review time, was rejected because it freezes the analysis to defend the bookkeeping.

## Consequences

- Case IDs are display identifiers derived from sorted member ticket numbers, not storage keys.
- Carry-forward to a later Snapshot can match pairs by ticket number, which the PRD's revalidation rule requires anyway.
