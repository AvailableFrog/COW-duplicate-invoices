"""The plan provider adapter (ADR 0001): what translates a question into a query plan.

Release one has no model, so the only provider is the null provider, which
proposes no plan; the Explore tab's plan comes from its chips. The adapter
exists so the plan contract is exercised now: whatever a provider proposes
is untrusted and goes through the same validator as the chips' plan before
anything runs. Release two puts a local open-weights model behind this
interface; a hosted paid API is ruled out.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class Proposal:
    """A provider's answer: a plan to validate (never numbers), or None with a message saying why not."""

    plan: dict[str, Any] | None
    message: str


class PlanProvider(Protocol):
    id: str
    label: str

    def propose(self, question: str) -> Proposal:
        """A plan for the question, which is untrusted text and never an instruction to the application."""
        ...

    def payload(self) -> dict[str, Any]:
        ...


class NullProvider:
    """The release-one provider: no model, no inference cost, no plan."""

    id = "none"
    label = "No model (release one)"

    def propose(self, question: str) -> Proposal:
        return Proposal(
            plan=None,
            message=(
                "Release one has no language model, so questions are not translated into plans. "
                "Build the plan with the Explore chips, or start from one of the starter questions."
            ),
        )

    def payload(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label, "proposes_plans": False}
