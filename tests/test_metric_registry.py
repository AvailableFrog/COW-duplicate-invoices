"""Ticket #4: one versioned metric registry, served by the API."""

PRD_METRIC_IDS = [
    "ticket_count", "flagged_duplicate_count", "unflagged_exact_repeat_count", "candidate_ticket_count",
    "pending_count", "approved_not_keyed_count", "pending_submission_age_days",
    "approved_not_keyed_submission_age_days", "claimed_hours", "employee_label_count",
    "submission_lag_days", "observed_approval_interval_hours", "known_base_value_bbd",
]
# Ticket #13: the value-context panel's other figures, each a registry metric (decision-log entry 60).
VALUE_PANEL_METRIC_IDS = [
    "flagged_duplicate_base_value_bbd", "unflagged_exact_repeat_extra_claim_bbd", "reviewed_known_base_value_bbd",
]

# Ticket #15: the Data readiness counts that are Ticket metrics (decision-log entry 70).
READINESS_METRIC_IDS = [
    "ambiguous_interval_ticket_count", "anomalous_date_count", "description_date_conflict_count", "missing_rate_count",
    "missing_required_field_count",
]

METRIC_ATTRIBUTES = {
    "id", "label", "definition", "unit", "grain", "allowed_dimensions", "null_treatment",
    "date_basis", "exclusions", "lineage",
}


def test_the_registry_declares_the_thirteen_prd_metrics_the_value_panel_and_readiness_figures_and_a_version(app):
    body = app.get("/api/metrics").json()

    assert body["registry_version"]
    assert body["versions"]["registry"] == body["registry_version"]
    # Ticket #33 adds the claimed-hours panel's reviewed alternative right after the metric it adjusts.
    expected = PRD_METRIC_IDS + VALUE_PANEL_METRIC_IDS + READINESS_METRIC_IDS
    expected.insert(expected.index("claimed_hours") + 1, "reviewed_claimed_hours")
    assert [metric["id"] for metric in body["metrics"]] == expected


def test_every_metric_states_each_attribute_the_prd_requires(app):
    metrics = app.get("/api/metrics").json()["metrics"]

    for metric in metrics:
        missing = METRIC_ATTRIBUTES - metric.keys()
        assert not missing, f"{metric['id']} lacks {sorted(missing)}"
        assert metric["label"] and metric["definition"] and metric["unit"] and metric["grain"]
        assert metric["null_treatment"] and metric["lineage"]


def test_the_metrics_fed_by_matching_rules_are_computed_now_the_strict_rule_exists(app):
    metrics = {metric["id"]: metric for metric in app.get("/api/metrics").json()["metrics"]}

    for metric_id in ("unflagged_exact_repeat_count", "candidate_ticket_count"):
        assert metrics[metric_id]["availability"]["status"] == "available"
    assert metrics["unflagged_exact_repeat_count"]["grain"] == "Possible duplicate"
