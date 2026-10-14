---
status: accepted
---

# The real workbook is committed to this private repository

The PRD says to keep example data local and never publish employee records in a public repository or hosted demo. This repository is private, and development happens in cloud sessions that start from a fresh clone, so keeping the workbook out of git would mean re-uploading it every session and the acceptance tests that cite real rows could never run there. We decided to commit `Labour Tickets Export.xlsx` under `data/` and treat the repository's privacy as the control. If the repository is ever made public or the code is reused elsewhere, the workbook must be purged from history first, not just deleted.

## Consequences

- A synthetic same-schema fixture is deferred to release two; it is still needed for the 50,000-row performance test.
- Any workbook a user imports locally outside `data/` is gitignored.
