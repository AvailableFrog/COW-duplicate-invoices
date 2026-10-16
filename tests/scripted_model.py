"""A scripted stand-in for Ollama's /api/chat, for testing the provider adapter at the API seam (ticket #42).

It answers each question from a script keyed by the question's text, so a
test decides exactly what "the model" says: a JSON answer, raw text, an HTTP
error or a delay. It records every request, so a test can check what was
sent. `oracle(suite)` scripts the evaluation suite's expected answers, which
makes the runner's own scoring testable without a model.

Run it on its own for the browser tests or a manual check:

    python tests/scripted_model.py --cases evals/nl-questions.json [--extra script.json]

It prints "Listening on http://127.0.0.1:PORT" once it is ready.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

QUESTION_PREFIXES = ("Follow-up question: ", "Question: ")


def question_of(body: dict[str, Any]) -> str:
    """The question in the last user message, as questions.user_prompt writes it."""
    content = next(message["content"] for message in reversed(body["messages"]) if message["role"] == "user")
    for line in reversed(content.splitlines()):
        for prefix in QUESTION_PREFIXES:
            if line.startswith(prefix):
                return line[len(prefix):]
    return content


def oracle(suite: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """What a perfect model would answer to every case, plus each scripted case's misbehaviour."""
    script: dict[str, dict[str, Any]] = {}
    for case in suite["cases"]:
        if case["question"] in script:
            continue  # the same words asked again without an earlier chart are answered by a guard, not the model
        if "script" in case:
            script[case["question"]] = case["script"]
            continue
        expect = case["expect"]
        expect = expect["any_of"][0] if "any_of" in expect else expect
        kind = expect.get("kind") or expect["kind_in"][0]
        if kind == "plan" and "plan" in expect:
            answer = {"kind": "plan", "plan": expect["plan"]}
        elif kind == "plan":
            answer = {"kind": "plan", "plan": EMPTY_PLAN}
        elif kind == "view":
            answer = {"kind": "view", "view_id": expect["view_id"]}
        elif kind == "clarify":
            answer = {"kind": "clarify", "clarifying_question": "Which do you mean?", "options": ["The first", "The second"]}
        else:
            answer = {"kind": "unsupported"}
        script[case["question"]] = {"answer": answer}
    return script


# The plan for the empty-result case: pending tickets created in January 2020, of which there are none.
EMPTY_PLAN = {
    "metric_id": "ticket_count", "group_by": ["Approval Status"],
    "filters": [{"field": "Approval Status", "operator": "eq", "value": "Pending"}],
    "date_basis": "Created", "date_range": {"from": "2020-01-01", "to": "2020-01-31"},
    "chart": "bar_vertical", "sort": "metric_desc", "limit": 10, "include_other": True,
}


class ScriptedModel:
    def __init__(self, script: dict[str, dict[str, Any]], default: dict[str, Any] | None = None) -> None:
        self.script = script
        self.default = default or {"answer": {"kind": "unsupported"}}
        self.requests: list[dict[str, Any]] = []
        model = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:  # keep test output quiet
                pass

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length))
                model.requests.append(body)
                behaviour = model.script.get(question_of(body), model.default)
                if "sleep" in behaviour:
                    time.sleep(behaviour["sleep"])
                if "status" in behaviour:
                    self.send_response(behaviour["status"])
                    self.end_headers()
                    self.wfile.write(b'{"error": "scripted failure"}')
                    return
                content = behaviour["raw"] if "raw" in behaviour else json.dumps(behaviour.get("answer", {"kind": "unsupported"}))
                payload = json.dumps({"model": body.get("model"), "message": {"role": "assistant", "content": content}, "done": True}).encode()
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # the caller gave up waiting

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> ScriptedModel:
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.server.shutdown()
        self.server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A scripted stand-in for Ollama's /api/chat.")
    parser.add_argument("--cases", type=Path, default=Path("evals/nl-questions.json"))
    parser.add_argument("--extra", type=Path, help="a JSON object of question -> behaviour, added to the oracle")
    args = parser.parse_args(argv)
    script = oracle(json.loads(args.cases.read_text()))
    if args.extra:
        script.update(json.loads(args.extra.read_text()))
    with ScriptedModel(script) as model:
        print(f"Listening on {model.url}", flush=True)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
