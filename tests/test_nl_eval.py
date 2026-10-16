"""Ticket #42: the natural-language evaluation suite and its runner.

The suite holds the PRD's 14 canonical questions, two paraphrases of each and
the safety cases. The runner is checked against the scripted stand-in: a
perfect stand-in meets every gate, and a wrong one is reported case by case
with the numerator, denominator and model configuration.
"""

import json
from collections import Counter

import pytest

from conftest import REPO_ROOT
from scripted_model import ScriptedModel, oracle

from labour_ticket_analytics.nl_eval import DEFAULT_CASES, evaluate, main, markdown
from labour_ticket_analytics.plans import validate
from labour_ticket_analytics.providers import OllamaProvider
from labour_ticket_analytics.schema import OPTIONAL_COLUMNS, REQUIRED_COLUMNS

SUITE = json.loads(DEFAULT_CASES.read_text())
FIELDS = (*REQUIRED_COLUMNS, *OPTIONAL_COLUMNS)


def test_the_suite_has_the_fourteen_canonical_questions_two_paraphrases_each_and_safety_cases():
    groups = Counter(case["group"] for case in SUITE["cases"])
    canonical = [case for case in SUITE["cases"] if case["group"] == "canonical"]
    paraphrases = Counter(case["of"] for case in SUITE["cases"] if case["group"] == "paraphrase")

    assert len({case["question"] for case in canonical}) == 14
    assert groups["paraphrase"] == 28 and set(paraphrases.values()) == {2}
    assert groups["safety"] >= 15
    assert len({case["id"] for case in SUITE["cases"]}) == len(SUITE["cases"])
    covered = " ".join(case["note"] for case in SUITE["cases"] if "note" in case).casefold()
    for topic in ("mutation", "identity", "payment", "unknown field", "prompt injection", "invalid model output",
                  "empty result", "provider failure", "timeout"):
        assert topic in covered, topic


def test_every_expected_plan_in_the_suite_is_valid():
    for case in SUITE["cases"]:
        expect = case["expect"]
        for option in expect.get("any_of", [expect]):
            if "plan" in option:
                validate(option["plan"], FIELDS)
    for plan in SUITE["previous_plans"].values():
        validate(plan, FIELDS)


@pytest.fixture(scope="module")
def perfect():
    with ScriptedModel(oracle(SUITE)) as model:
        yield evaluate(OllamaProvider("scripted-oracle", model.url, 10), runs=2, include_scripted=True)


def test_a_perfect_stand_in_meets_every_gate_with_the_prd_numbers(perfect):
    assert perfect["meets_release_two_gate"] is True
    assert perfect["failures"] == []
    assert {group: (scores["passed"], scores["total"]) for group, scores in perfect["groups"].items()} == {
        "canonical": (15, 15), "paraphrase": (28, 28), "safety": (19, 19),
    }
    assert perfect["prompt_leaks"] == [] and perfect["workbook"]["unchanged"] is True
    assert perfect["runs"] == 2 and perfect["variability"]["unstable_cases"] == []


def test_the_report_names_the_model_and_its_configuration(perfect):
    text = markdown(perfect)

    assert perfect["provider"]["model"] == "scripted-oracle"
    assert perfect["provider"]["options"] == {"temperature": 0, "seed": 7}
    assert "| canonical | 15 | 15 | 100% | 100% met |" in text
    assert "not a production accuracy guarantee" in text


def test_a_wrong_model_is_scored_case_by_case(tmp_path):
    script = oracle(SUITE)
    # Wrong grouping for one canonical question, a wrong chart for a paraphrase, a wrong view, and an invalid answer.
    script["Show ticket counts by approval status."] = {"answer": {"kind": "plan", "plan": {**SUITE["cases"][0]["expect"]["plan"], "group_by": ["Keyed"]}}}
    script["Count the pending tickets for each supervisor."] = {"answer": {"kind": "plan", "plan": {**script["Count the pending tickets for each supervisor."]["answer"]["plan"], "chart": "table"}}}
    script["Show dates that need checking."] = {"answer": {"kind": "view", "view_id": "value_context"}}
    script["Show tickets by pay grade."] = {"raw": "not json"}
    with ScriptedModel(script) as model:
        result = evaluate(OllamaProvider("scripted-wrong", model.url, 10))

    failed = {failure["id"]: failure["reason"] for failure in result["failures"]}
    assert set(failed) == {"c01", "c06b", "c10"}
    assert "grouped by ['Keyed']" in failed["c01"]
    assert "chart table" in failed["c06b"]
    assert "view value_context" in failed["c10"]
    assert result["groups"]["canonical"] == {**result["groups"]["canonical"], "passed": 13, "total": 15, "meets_gate": False}
    assert result["groups"]["paraphrase"]["passed"] == 27 and result["groups"]["paraphrase"]["meets_gate"] is True
    # Against a model that cannot misbehave on purpose, the scripted-only cases are skipped and listed.
    assert result["skipped_scripted_cases"] == ["m01", "m02", "m03", "m04", "m05", "m06", "m07"]
    assert result["meets_release_two_gate"] is False


def test_the_runner_writes_its_report_and_exits_with_the_gate(tmp_path):
    out = tmp_path / "report.json"
    with ScriptedModel(oracle(SUITE)) as model:
        code = main(["--model", "scripted", "--ollama-url", model.url, "--runs", "1", "--out", str(out)])

    assert code == 0
    written = json.loads(out.read_text())
    assert written["groups"]["canonical"]["passed"] == 15 and written["skipped_scripted_cases"]
    assert out.with_suffix(".md").read_text().startswith("# Natural-language evaluation: scripted")


def test_the_runner_refuses_a_model_service_off_loopback():
    with pytest.raises(ValueError, match="loopback"):
        main(["--model", "m", "--ollama-url", "http://example.com:11434"])


def test_the_suite_is_committed_at_the_documented_path():
    assert DEFAULT_CASES == REPO_ROOT / "evals" / "nl-questions.json"
