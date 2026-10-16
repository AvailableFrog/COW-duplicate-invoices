"""The plan provider adapter (ADR 0001): what translates a question into a query plan.

A provider proposes an answer to a question: a plan, an Overview view, a
clarifying question, or "unsupported". Whatever it proposes is untrusted and
goes through the same validator as the chips' plan before anything runs
(questions.py). Two providers exist. The null provider, used when no model is
configured, proposes nothing, so the Explore tab works from its chips alone.
The Ollama provider asks a local open-weights model through Ollama's HTTP API
on loopback; a hosted paid API is ruled out, and a provider address off
loopback is refused at launch. Only the prompt (the plan contract, metric
definitions, field allowlists, the as-of date, the current plan for a
follow-up, and the question) is sent; never a workbook row.
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlsplit

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_TIMEOUT_SECONDS = 60.0
# A model answer longer than this is refused unread.
MAX_RESPONSE_BYTES = 64 * 1024


@dataclass(frozen=True)
class Proposal:
    """A provider's answer: `answer` is the model's JSON object (untrusted), or None with a message saying why not."""

    answer: dict[str, Any] | None
    message: str
    # What went wrong when there is no answer: no_model, timeout, unreachable, provider_error, invalid_output.
    failure: str | None = None
    elapsed_seconds: float | None = None


class ProviderError(RuntimeError):
    pass


class PlanProvider(Protocol):
    id: str
    label: str
    timeout_seconds: float

    def propose(self, prompt: Prompt) -> Proposal:
        """An answer to the question, which is untrusted text and never an instruction to the application."""
        ...

    def payload(self) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class Prompt:
    """Everything a provider may send: instructions and allowlists (system), and the question with its context (user)."""

    system: str
    user: str
    response_schema: dict[str, Any] = field(default_factory=dict)


class NullProvider:
    """No model configured: no inference, no plan; the chips build every chart."""

    id = "none"
    label = "No model configured"
    timeout_seconds = DEFAULT_TIMEOUT_SECONDS

    def propose(self, prompt: Prompt) -> Proposal:
        return Proposal(
            answer=None,
            failure="no_model",
            message=(
                "No language model is configured, so questions are not translated into plans. Build the chart with "
                "the chips or a starter question, or relaunch with --model and a local Ollama model (see the README)."
            ),
        )

    def payload(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label, "proposes_plans": False, "model": None, "timeout_seconds": self.timeout_seconds}


class OllamaProvider:
    """A local open-weights model served by Ollama on loopback, asked for one JSON answer per question."""

    id = "ollama"

    def __init__(
        self, model: str, base_url: str = DEFAULT_OLLAMA_URL, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        seed: int = 7,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.seed = seed
        self.label = f"{model} (local, Ollama)"
        # Loopback never goes through a proxy, whatever the environment says.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def options(self) -> dict[str, Any]:
        """The generation settings sent with every question, reported beside every evaluation."""
        return {"temperature": 0, "seed": self.seed}

    def request_body(self, prompt: Prompt) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": [{"role": "system", "content": prompt.system}, {"role": "user", "content": prompt.user}],
            "stream": False,
            "format": prompt.response_schema or "json",
            "options": self.options(),
        }

    def propose(self, prompt: Prompt) -> Proposal:
        body = json.dumps(self.request_body(prompt)).encode()
        request = urllib.request.Request(
            f"{self.base_url}/api/chat", data=body, headers={"Content-Type": "application/json"}, method="POST",
        )
        started = time.monotonic()
        try:
            with self._opener.open(request, timeout=self.timeout_seconds) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except (TimeoutError, socket.timeout):
            return self._failed("timeout", f"The model did not answer within {self.timeout_seconds:g} seconds.", started)
        except urllib.error.HTTPError as error:
            return self._failed("provider_error", f"The model service answered with an error (HTTP {error.code}).", started)
        except urllib.error.URLError as error:
            if isinstance(error.reason, (TimeoutError, socket.timeout)):
                return self._failed("timeout", f"The model did not answer within {self.timeout_seconds:g} seconds.", started)
            return self._failed(
                "unreachable",
                f"The model service at {self.base_url} could not be reached. Start Ollama, or check --ollama-url.",
                started,
            )
        elapsed = time.monotonic() - started
        if len(raw) > MAX_RESPONSE_BYTES:
            return self._failed("invalid_output", "The model's answer was too long to be a plan.", started)
        try:
            envelope = json.loads(raw)
            content = envelope["message"]["content"]
            answer = json.loads(content)
        except (ValueError, KeyError, TypeError):
            return self._failed("invalid_output", "The model's answer was not the JSON object the plan contract asks for.", started)
        if not isinstance(answer, dict):
            return self._failed("invalid_output", "The model's answer was not the JSON object the plan contract asks for.", started)
        return Proposal(answer=answer, message="", elapsed_seconds=round(elapsed, 2))

    def _failed(self, failure: str, message: str, started: float) -> Proposal:
        return Proposal(answer=None, failure=failure, message=message, elapsed_seconds=round(time.monotonic() - started, 2))

    def payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "proposes_plans": True,
            "model": self.model,
            "url": self.base_url,
            "timeout_seconds": self.timeout_seconds,
            "options": self.options(),
        }


def require_loopback_url(url: str, is_loopback) -> None:
    """The model service must be on this machine: nothing about the export may leave it."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"the model service address {url!r} is not an http URL")
    if not is_loopback(parts.hostname):
        raise ValueError(f"refusing the model service at {url!r}: it must be on loopback, so no data leaves this machine")
