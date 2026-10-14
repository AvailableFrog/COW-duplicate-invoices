"""The supplied export schema: which columns a workbook must carry and which it may.

Required columns block activation when absent. Optional columns are preserved
when present; when absent, the features that read them are disabled and the
Snapshot header says which and why (PRD section 8).
"""

from __future__ import annotations

from typing import Any

REQUIRED_COLUMNS = (
    "Employee", "Ticket Number", "Job Number", "Date", "Time", "Regular Hours", "Overtime",
    "Double Time", "Job Work Pay", "Approval Status", "Keyed", "Created",
)

OPTIONAL_COLUMNS = (
    "Occupation", "Job Name", "Description of Job Work", "Modified", "ID", "Email Address",
    "Rate", "Date Approved", "Supervisor", "Modified By",
)


def missing_required_columns(fields: tuple[str, ...]) -> list[str]:
    present = set(fields)
    return [name for name in REQUIRED_COLUMNS if name not in present]


def repeated_schema_columns(fields: tuple[str, ...]) -> list[str]:
    """Schema columns named more than once, which would make the mapping ambiguous."""
    return [name for name in (*REQUIRED_COLUMNS, *OPTIONAL_COLUMNS) if fields.count(name) > 1]


# What each optional column feeds, and the plain-language consequence of its
# absence. Kinds: "metric" (a metric registry ID), "grouping" (a dimension for
# grouping and filtering), "check" (a matching rule or data check), "display"
# (a field shown in the evidence drawer).
OPTIONAL_COLUMN_DEPENDENTS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "Occupation": (
        ("grouping", "Occupation", "Tickets cannot be grouped or filtered by occupation."),
    ),
    "Job Name": (
        ("grouping", "Job Name", "jobs are identified by Job Number only."),
    ),
    "Description of Job Work": (
        ("check", "description_date_exception",
         "service dates written in descriptions cannot be compared with Date."),
        ("display", "Description of Job Work", "the evidence drawer cannot show what work was described."),
    ),
    "Modified": (
        ("display", "Modified", "the claim timeline cannot show when a Ticket was last modified."),
    ),
    "ID": (
        ("check", "id_uniqueness",
         "ID uniqueness cannot be validated; Tickets are still identified by their Excel row."),
    ),
    "Email Address": (
        ("display", "Email Address", "the evidence drawer cannot show the employee email address."),
    ),
    "Rate": (
        ("metric", "known_base_value_bbd", "labour cannot be priced and the base value is unavailable."),
    ),
    "Date Approved": (
        ("metric", "observed_approval_interval_hours",
         "the time from Created to approval cannot be measured."),
        ("display", "Date Approved", "the claim timeline cannot show when a Ticket was approved."),
    ),
    "Supervisor": (
        ("grouping", "Supervisor", "Tickets cannot be grouped or filtered by supervisor."),
    ),
    "Modified By": (
        ("display", "Modified By", "the evidence drawer cannot show who last modified a Ticket."),
    ),
}


def missing_optional_columns(fields: tuple[str, ...]) -> list[str]:
    present = set(fields)
    return [name for name in OPTIONAL_COLUMNS if name not in present]


def disabled_features(fields: tuple[str, ...]) -> list[dict[str, Any]]:
    """One entry per feature switched off by an absent optional column."""
    return [
        {
            "column": column,
            "kind": kind,
            "feature": feature,
            "reason": f"The workbook has no {column} column, so {consequence}",
        }
        for column in missing_optional_columns(fields)
        for kind, feature, consequence in OPTIONAL_COLUMN_DEPENDENTS[column]
    ]
