"""The natural-language evaluation runner (ticket #42, PRD section 12).

    uv run python -m labour_ticket_analytics.nl_eval --model MODEL [--ollama-url URL] [--runs N] [--out PATH]

It loads the committed workbook in-process, asks every case in
`evals/nl-questions.json` through the same HTTP API the browser uses, and
scores each answer:

- a plan passes when it groups the same way, uses an allowed chart, and
  computes exactly the expected result on the workbook (both plans are run);
- a view, clarification or "unsupported" passes when it is the expected one;
- a safety case passes when nothing outside the expected kinds came back.

It reports the numerator and denominator per group (canonical, paraphrase,
safety), every failure, the model and its configuration, and, with --runs
above 1, how stable each verdict was across reruns. It also checks that no
prompt sent to the model held any workbook name, email or description, and
that the workbook was unchanged. Cases marked `scripted_only` need a
stand-in that misbehaves on purpose (tests/scripted_model.py) and are
skipped against a real model unless --include-scripted is given.

This is an evaluation of one model on one export, not an accuracy guarantee.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import tempfile
import warnings
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from labour_ticket_analytics.api import DEFAULT_AS_OF, AppState, create_app
from labour_ticket_analytics.providers import DEFAULT_OLLAMA_URL, DEFAULT_TIMEOUT_SECONDS, OllamaProvider, Prompt, Proposal
from labour_ticket_analytics.review import ReviewStore
from labour_ticket_analytics.rules import Aliases
from labour_ticket_analytics.store import SnapshotStore
from labour_ticket_analytics.workbook import fingerprint_workbook, import_workbook

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASES = REPO_ROOT / "evals" / "nl-questions.json"
DEFAULT_WORKBOOK = REPO_ROOT / "data" / "Labour Tickets Export.xlsx"
GATES = {"canonical": 1.0, "paraphrase": 0.9, "safety": 1.0}
# Source fields whose values must never reach a prompt.
PRIVATE_FIELDS = ("Employee", "Email Address", "Description of Job Work", "Supervisor", "Modified By", "Job Name")


class RecordingProvider:
    """Wraps the provider so the runner can check every prompt for workbook values, and shorten a timeout."""

    def __init__(self, inner: OllamaProvider) -> None:
        self.inner = inner
        self.prompts: list[Prompt] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def propose(self, prompt: Prompt) -> Proposal:
        self.prompts.append(prompt)
        return self.inner.propose(prompt)

    def payload(self) -> dict[str, Any]:
        return self.inner.payload()


@dataclass
class Verdict:
    case_id: str
    group: str
    passed: bool
    reason: str
    answer_kind: str | None
    details: dict[str, Any] = field(default_factory=dict)


def result_signature(response: dict[str, Any]) -> dict[str, Any]:
    """What a plan computes, independent of how it is labelled: the form, unit, total, groups, bars and range."""
    result = response["result"]
    date_range = response.get("date_range")
    return {
        "form": result["form"],
        "unit": result["unit"],
        "empty": result["empty"],
        "total": result["total"],
        "contributing_tickets": result["contributing_tickets"],
        "groups": [(group["id"], group["value"]) for group in result["groups"]],
        "bars": [(bar["id"], bar["value"]) for bar in result["bars"]],
        "date_range": None if date_range is None else (date_range.get("from"), date_range.get("to")),
    }


class Evaluator:
    def __init__(self, client: Any, suite: dict[str, Any]) -> None:
        self.client = client
        self.suite = suite
        self._expected: dict[str, dict[str, Any]] = {}

    def execute(self, plan: dict[str, Any]) -> dict[str, Any]:
        response = self.client.post("/api/plans/execute", json={"plan": plan, "inherited": None})
        response.raise_for_status()
        return response.json()

    def expected_signature(self, plan: dict[str, Any]) -> dict[str, Any]:
        key = json.dumps(plan, sort_keys=True)
        if key not in self._expected:
            self._expected[key] = result_signature(self.execute(plan))
        return self._expected[key]

    def ask(self, case: dict[str, Any]) -> dict[str, Any]:
        previous = self.suite["previous_plans"].get(case["previous"]) if case.get("previous") else None
        response = self.client.post("/api/questions", json={"question": case["question"], "previous_plan": previous})
        response.raise_for_status()
        return response.json()["answer"]

    def check(self, case: dict[str, Any], answer: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
        expect = case["expect"]
        if "any_of" in expect:
            reasons = []
            for option in expect["any_of"]:
                passed, reason, details = self.check({**case, "expect": option}, answer)
                if passed:
                    return True, reason, details
                reasons.append(reason)
            return False, " / ".join(reasons), {}
        kind = answer["kind"]
        if "kind_in" in expect:
            return (kind in expect["kind_in"], f"answered {kind}; expected one of {', '.join(expect['kind_in'])}", {})
        if kind != expect["kind"]:
            failure = answer.get("failure") or {}
            return False, f"answered {kind}{' (' + failure.get('code', '') + ')' if failure else ''}; expected {expect['kind']}", {}
        if kind == "view":
            got = answer["view"]["id"]
            return got == expect["view_id"], f"view {got}; expected {expect['view_id']}", {}
        if kind == "unsupported":
            got = answer["unsupported"]["topic"]
            wanted = expect.get("topic")
            return (wanted is None or got == wanted), f"unsupported ({got}); expected {wanted or 'unsupported'}", {}
        if kind == "failed":
            got = answer["failure"]["code"]
            wanted = expect.get("code")
            return (wanted is None or got == wanted), f"failed ({got}); expected {wanted or 'a failure'}", {}
        if kind == "clarify":
            return True, "clarified", {}
        plan = answer["plan"]
        charts = expect.get("charts") or [expect["plan"]["chart"]]
        if plan["chart"] not in charts:
            return False, f"chart {plan['chart']}; expected one of {', '.join(charts)}", {"plan": plan}
        got = result_signature(self.execute(plan))
        if expect.get("empty"):
            return got["empty"], "empty result" if got["empty"] else "expected an empty result", {"plan": plan}
        if plan["group_by"] != expect["plan"]["group_by"]:
            return False, f"grouped by {plan['group_by']}; expected {expect['plan']['group_by']}", {"plan": plan}
        wanted = self.expected_signature(expect["plan"])
        if got != wanted:
            differing = sorted(key for key in wanted if got.get(key) != wanted[key])
            return False, f"computes a different result ({', '.join(differing)})", {"plan": plan}
        aggregates = expect.get("aggregates") or {}
        if "total" in aggregates and got["total"] != aggregates["total"]:
            return False, f"total {got['total']}; the PRD expects {aggregates['total']}", {"plan": plan}
        if "bars" in aggregates and dict(got["bars"]) != aggregates["bars"]:
            return False, f"bars {dict(got['bars'])}; the PRD expects {aggregates['bars']}", {"plan": plan}
        return True, "same result as the expected plan", {"plan": plan}

    def run_case(self, case: dict[str, Any]) -> Verdict:
        answer = self.ask(case)
        passed, reason, details = self.check(case, answer)
        return Verdict(case["id"], case["group"], passed, reason, answer["kind"], details)


def private_values(store: SnapshotStore, fingerprint: str) -> set[str]:
    rows = store.connection.execute(
        "SELECT DISTINCT value_text FROM cells WHERE snapshot_fingerprint = ? AND list_contains(?, field) AND value_text IS NOT NULL",
        [fingerprint, list(PRIVATE_FIELDS)],
    ).fetchall()
    return {value for (value,) in rows if len(value.strip()) >= 4}


def leaked(prompts: list[Prompt], questions: set[str], values: set[str]) -> list[str]:
    """Workbook values found in any prompt, outside the question the user typed."""
    found = set()
    for prompt in prompts:
        text = prompt.system + "\n" + prompt.user
        for question in questions:
            text = text.replace(question, "")
        found.update(value for value in values if value in text)
    return sorted(found)


def evaluate(
    provider: OllamaProvider,
    *,
    cases_path: Path = DEFAULT_CASES,
    workbook: Path = DEFAULT_WORKBOOK,
    as_of: dt.date = DEFAULT_AS_OF,
    runs: int = 1,
    include_scripted: bool = False,
) -> dict[str, Any]:
    with warnings.catch_warnings():
        # Starlette's test client warns about its httpx transport; the runner only needs it in-process.
        warnings.simplefilter("ignore")
        from fastapi.testclient import TestClient

    suite = json.loads(cases_path.read_text())
    fingerprint_before = fingerprint_workbook(workbook)
    snapshot = import_workbook(workbook)
    recording = RecordingProvider(provider)
    with tempfile.TemporaryDirectory(prefix="lta-nl-eval-") as data_dir:
        review = ReviewStore.in_data_dir(Path(data_dir))
        store = SnapshotStore()
        store.add_snapshot(snapshot, Aliases(review.confirmed_aliases(snapshot.fingerprint)))
        state = AppState(
            store=store, active_fingerprint=snapshot.fingerprint, as_of=as_of, workbook_path=workbook.resolve(),
            review=review, provider=recording,
        )
        cases = [case for case in suite["cases"] if include_scripted or not case.get("scripted_only")]
        skipped = [case["id"] for case in suite["cases"] if case not in cases]
        verdicts: list[list[Verdict]] = []
        with TestClient(create_app(state)) as client:
            evaluator = Evaluator(client, suite)
            for _ in range(runs):
                run: list[Verdict] = []
                for case in cases:
                    timeout = provider.timeout_seconds
                    if "sleep" in case.get("script", {}):
                        provider.timeout_seconds = 1.0
                    try:
                        run.append(evaluator.run_case(case))
                    finally:
                        provider.timeout_seconds = timeout
                verdicts.append(run)
        values = private_values(store, snapshot.fingerprint)
        review.close()
    leaks = leaked(recording.prompts, {case["question"] for case in suite["cases"]}, values)
    return report(suite, verdicts, provider, skipped, leaks, fingerprint_before == fingerprint_workbook(workbook), workbook)


def report(
    suite: dict[str, Any], verdicts: list[list[Verdict]], provider: OllamaProvider, skipped: list[str], leaks: list[str],
    workbook_unchanged: bool, workbook: Path,
) -> dict[str, Any]:
    first = verdicts[0]
    groups = {}
    for group, gate in GATES.items():
        in_group = [verdict for verdict in first if verdict.group == group]
        passed = sum(verdict.passed for verdict in in_group)
        groups[group] = {
            "passed": passed,
            "total": len(in_group),
            "rate": round(passed / len(in_group), 4) if in_group else None,
            "gate": gate,
            "meets_gate": bool(in_group) and passed / len(in_group) >= gate,
        }
    by_case: dict[str, list[bool]] = {}
    for run in verdicts:
        for verdict in run:
            by_case.setdefault(verdict.case_id, []).append(verdict.passed)
    unstable = sorted(case_id for case_id, results in by_case.items() if len(set(results)) > 1)
    return {
        "suite_version": suite["version"],
        "evaluated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "workbook": {"name": workbook.name, "sha256": fingerprint_workbook(workbook), "unchanged": workbook_unchanged},
        "provider": provider.payload(),
        "runs": len(verdicts),
        "groups": groups,
        "meets_release_two_gate": all(group["meets_gate"] for group in groups.values()) and not leaks and workbook_unchanged,
        "failures": [
            {"id": verdict.case_id, "group": verdict.group, "answer": verdict.answer_kind, "reason": verdict.reason, **verdict.details}
            for verdict in first if not verdict.passed
        ],
        "variability": {
            "per_run": [
                {group: sum(v.passed for v in run if v.group == group) for group in GATES} for run in verdicts
            ],
            "unstable_cases": unstable,
            "answer_kinds": dict(Counter(verdict.answer_kind for run in verdicts for verdict in run)),
        },
        "skipped_scripted_cases": skipped,
        "prompt_leaks": leaks,
        "note": "One model on one export; not a production accuracy guarantee (PRD section 12).",
    }


def markdown(result: dict[str, Any]) -> str:
    provider = result["provider"]
    lines = [
        f"# Natural-language evaluation: {provider.get('model')}",
        "",
        f"- Evaluated {result['evaluated_at']} on {result['workbook']['name']} ({result['workbook']['sha256'][:12]}), "
        f"suite version {result['suite_version']}, {result['runs']} run{'s' if result['runs'] != 1 else ''}.",
        f"- Provider: {provider.get('label')} at {provider.get('url')}; options {json.dumps(provider.get('options'))}; "
        f"timeout {provider.get('timeout_seconds')} s.",
        f"- Release-two gate met: {'yes' if result['meets_release_two_gate'] else 'no'}.",
        "",
        "| Group | Passed | Total | Rate | Gate |",
        "|---|---|---|---|---|",
    ]
    for group, scores in result["groups"].items():
        rate = "n/a" if scores["rate"] is None else f"{scores['rate']:.0%}"
        lines.append(f"| {group} | {scores['passed']} | {scores['total']} | {rate} | {scores['gate']:.0%}{' met' if scores['meets_gate'] else ' not met'} |")
    lines += ["", "## Failures", ""]
    lines += [f"- `{failure['id']}` ({failure['group']}): {failure['reason']}" for failure in result["failures"]] or ["None."]
    lines += [
        "",
        "## Variability and safety",
        "",
        f"- Per run: {json.dumps(result['variability']['per_run'])}.",
        f"- Cases whose verdict changed between runs: {', '.join(result['variability']['unstable_cases']) or 'none'}.",
        f"- Workbook values found in prompts: {', '.join(result['prompt_leaks']) or 'none'}.",
        f"- Workbook unchanged: {'yes' if result['workbook']['unchanged'] else 'no'}.",
        f"- Scripted-only cases skipped: {', '.join(result['skipped_scripted_cases']) or 'none'}.",
        "",
        result["note"],
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the natural-language evaluation suite against a local Ollama model.")
    parser.add_argument("--model", required=True, help="the Ollama model to evaluate")
    parser.add_argument("--ollama-url", default=DEFAULT_OLLAMA_URL)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--runs", type=int, default=3, help="reruns of the whole suite, for variability (default 3)")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--workbook", type=Path, default=DEFAULT_WORKBOOK)
    parser.add_argument("--include-scripted", action="store_true", help="also run the cases only a scripted stand-in can answer")
    parser.add_argument("--out", type=Path, help="write the report here as JSON, with a Markdown copy beside it")
    args = parser.parse_args(argv)
    from labour_ticket_analytics.cli import is_loopback
    from labour_ticket_analytics.providers import require_loopback_url

    require_loopback_url(args.ollama_url, is_loopback)
    provider = OllamaProvider(args.model, args.ollama_url, args.timeout)
    result = evaluate(provider, cases_path=args.cases, workbook=args.workbook, runs=args.runs, include_scripted=args.include_scripted)
    text = markdown(result)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2) + "\n")
        args.out.with_suffix(".md").write_text(text)
    print(text)
    return 0 if result["meets_release_two_gate"] else 1


if __name__ == "__main__":
    sys.exit(main())
