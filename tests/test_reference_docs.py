"""Ticket #18: the metric and rule reference is generated from the running service.

docs/metrics-and-rules.md is rendered from the metric registry and the rule
descriptions the API serves, so it cannot drift from the code. This test fails
when the committed file differs from what the service now says; regenerate it
with:

    LTA_WRITE_DOCS=1 uv run pytest tests/test_reference_docs.py
"""

from __future__ import annotations

import os
from pathlib import Path

from conftest import REPO_ROOT

REFERENCE = REPO_ROOT / "docs" / "metrics-and-rules.md"


def _value(item) -> str:
    if isinstance(item, dict):
        for key in ("label", "description", "reason", "id"):
            if item.get(key):
                text = str(item[key])
                code = item.get("id") if key != "id" else None
                return f"`{code}`: {text}" if code and code != text else text
        return ", ".join(f"{k}: {v}" for k, v in item.items())
    return str(item)


def _list(items) -> str:
    return "; ".join(_value(item) for item in items) if items else "none"


def render(registry: dict, rules: list[dict]) -> str:
    versions = registry["versions"]
    lines = [
        "# Metrics and matching rules",
        "",
        "Generated from the running service by `tests/test_reference_docs.py`; do not edit by hand.",
        f"Registry {versions['registry']}, rules {versions['rules']}, parser {versions['parser']}, app {versions['app']}.",
        "Every Overview tile, chart and Explore plan reads its numbers from these metrics, and every possible duplicate comes from these rules.",
        "",
        "## Metrics",
        "",
    ]
    for metric in registry["metrics"]:
        date_basis = metric["date_basis"]
        measured = date_basis.get("measured_on")
        lines += [
            f"### `{metric['id']}`: {metric['label']}",
            "",
            metric["definition"],
            "",
            "| Property | Value |",
            "|---|---|",
            f"| Unit | {metric['unit']} |",
            f"| Grain | {metric['grain']} |",
            f"| Statistic | {metric['statistic']} |",
            f"| Allowed dimensions | {_list(metric['allowed_dimensions'])} |",
            f"| Null treatment | {metric['null_treatment']} |",
            f"| Date basis | {'measured on ' + _value(measured) + '; ' if measured else ''}{date_basis['note']} |",
            f"| Exclusions | {_list(metric['exclusions'])} |",
            f"| Lineage | {metric['lineage']} |",
            f"| Percentage of | {('`' + metric['percentage_of'] + '`') if metric['percentage_of'] else 'none'} |",
            f"| Requires columns | {_list(metric['requires_columns'])} |",
            f"| Buckets | {_list(metric['buckets'])} |",
            f"| Reads review links | {'yes' if metric['reads_review_links'] else 'no'} |",
            "",
        ]
    lines += [
        "## Matching rules",
        "",
        "Each rule proposes Candidates between two Tickets; evidence strength describes the matching evidence, never payment or intent.",
        "",
        "| Rule | Pattern | Strength | Fields compared | Accepts a confirmed Alias | Reason shown |",
        "|---|---|---|---|---|---|",
    ]
    for rule in rules:
        lines.append(
            f"| `{rule['id']}` {rule['label']} | {rule['pattern']} | {rule['evidence_strength']} | "
            f"{', '.join(rule['fields_compared'])} | {'yes' if rule['accepts_alias'] else 'no'} | {rule['reason']} |"
        )
    return "\n".join(line.replace("\n", " ") for line in lines).rstrip() + "\n"


def test_the_metric_and_rule_reference_matches_what_the_service_serves(app):
    rendered = render(app.get("/api/metrics").json(), app.get("/api/review-priorities").json()["rules"])
    if os.environ.get("LTA_WRITE_DOCS") == "1":
        REFERENCE.write_text(rendered, encoding="utf-8")
    assert REFERENCE.exists(), "run LTA_WRITE_DOCS=1 uv run pytest tests/test_reference_docs.py"
    assert REFERENCE.read_text(encoding="utf-8") == rendered, (
        "docs/metrics-and-rules.md is out of date: run LTA_WRITE_DOCS=1 uv run pytest tests/test_reference_docs.py"
    )


def test_the_reference_covers_every_metric_and_rule(app):
    text = REFERENCE.read_text(encoding="utf-8")
    for metric in app.get("/api/metrics").json()["metrics"]:
        assert f"### `{metric['id']}`" in text
    for rule in app.get("/api/review-priorities").json()["rules"]:
        assert f"`{rule['id']}`" in text
