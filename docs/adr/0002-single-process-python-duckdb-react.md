---
status: accepted
---

# Single-process Python + DuckDB service serving a React/Vega-Lite frontend

The PRD recommends a Python data service with DuckDB, a React/TypeScript UI, and constrained Vega-Lite charts. We kept that stack because DuckDB gives the metric registry real analytical SQL over an immutable snapshot and Vega-Lite gives a validated chart specification instead of model-generated code. We rejected running it as two processes: the Python service serves the built frontend, binds to loopback only, and launches with one command, because the only user is one analyst on one machine and a reviewer should not need a Node dev server.

## Consequences

- Local Review Outcomes, Aliases, and their history live in one local DuckDB file next to the imported Snapshot, in tables physically separate from source Tickets. The workbook is read-only input; nothing is written back.
- Swapping the frontend later means rebuilding the UI, not the data layer.
