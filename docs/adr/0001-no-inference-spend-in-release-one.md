---
status: accepted
---

# No model inference spend; natural-language input deferred to release two

This is a prototype for a single consultant preparing for one meeting, and the engagement forbids sending confidential data to unapproved AI services. We decided release one carries no model provider at all: the "Ask the data" surface ships as a deterministic query-plan UI (metric, grouping, filter, and chart chips compiled to the same validated plan the PRD specifies), and natural-language translation is a release-two layer on top of it. Any future provider must cost nothing to run. The intended release-two path is a local open-weights model (for example via Ollama) behind the adapter; a hosted paid API is out. Nothing is built for it in release one.

## Consequences

- The provider adapter is built against a null provider so the plan contract and validation are exercised now.
- The PRD's held-out natural-language evaluation suite moves to release two with the feature.
