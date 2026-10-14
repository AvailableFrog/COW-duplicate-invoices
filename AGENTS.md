## Agent skills

### Issue tracker

Issues and specs live as GitHub Issues on `AvailableFrog/COW-duplicate-invoices`. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical labels, unchanged: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

### Branches and pull requests

Each ticket gets its own branch cut from the latest `main` and lands through a pull request whose body says `Closes #<n>`; the user reviews and merges it. Run `uv run pytest` and `npm --prefix frontend run typecheck` before opening the PR; CI runs both again on it.

Decisions a ticket raises go to the user in the PR description. Record them in `docs/decision-log.md` (and the PRD or glossary they change) only once the user approves them.
