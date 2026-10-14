"""Ticket #7: the possible-duplicate evidence behind the drawer, and the Annotations it carries.

A possible duplicate is addressed by any member Ticket (Snapshot and Excel
row), never by its display name. Expected source values are the "Exact source
rows" tables of docs/source/labour-ticket-report-readable.md.
"""

import datetime as dt

from conftest import HANDOFF_WORKBOOK_SHA256, running
from synthetic import ticket, write_workbook

SHEET = "Labour Tickets (1)"


def evidence(app, excel_row: int, fingerprint: str = HANDOFF_WORKBOOK_SHA256, **params) -> dict:
    response = app.get(f"/api/snapshots/{fingerprint}/tickets/{excel_row}/possible-duplicate", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def column(payload: dict, excel_row: int) -> dict[str, tuple[str, object]]:
    """One member's column of the transposed source table: field -> (raw type, value)."""
    index = [member["excel_row"] for member in payload["members"]].index(excel_row)
    return {row["field"]: (row["cells"][index]["raw_type"], row["cells"][index]["value"]) for row in payload["fields"]}


# C. Peter Holder, "Exact source rows: 620 / 855", with the report's ISO date display.
PETER_620 = {
    "Employee": ("str", "Peter Holder"),
    "Occupation": ("str", "Labourer"),
    "Ticket Number": ("str", "L225761"),
    "Job Name": ("str", "Beachlands"),
    "Job Number": ("int", 41215),
    "Date": ("datetime", "2026-09-28T00:00:00"),
    "Time": ("str", "7:30 am to 4:30 pm"),
    "Regular Hours": ("int", 8),
    "Overtime": ("int", 0),
    "Double Time": ("int", 0),
    "Job Work Pay": ("int", 0),
    "Description of Job Work": ("str", "None"),
    "Supervisor": ("str", "Jamar O'Neal"),
    "Approval Status": ("str", "Approved"),
    "Modified": ("datetime", "2026-10-05T07:48:00"),
    "Created": ("datetime", "2026-10-02T18:56:00"),
    "ID": ("int", 224761),
    "Email Address": ("str", "Nardyspringer@gmail.com"),
    "Keyed": ("bool", True),
    "Rate": ("float", 14.53),
    "Date Approved": ("datetime", "2026-10-05T07:42:00"),
    "Modified By": ("str", "Tracy Whitehall"),
}
PETER_855 = {
    **PETER_620,
    "Ticket Number": ("str", "L225526"),
    "Modified": ("datetime", "2026-10-01T13:44:00"),
    "Created": ("datetime", "2026-09-28T18:21:00"),
    "ID": ("int", 224526),
    "Date Approved": ("datetime", "2026-09-29T09:36:00"),
}
PETER_DIFFERENT = ["Ticket Number", "Modified", "Created", "ID", "Date Approved"]


def test_the_peter_holder_possible_duplicate_returns_both_members_with_all_22_fields_as_the_report_prints_them(app):
    peter = evidence(app, 620)

    assert peter["display_id"] == "Possible duplicate L225526+L225761"
    assert [member["excel_row"] for member in peter["members"]] == [855, 620]
    assert len(peter["fields"]) == 22
    assert column(peter, 620) == PETER_620
    assert column(peter, 855) == PETER_855
    assert [row["field"] for row in peter["fields"] if row["differs"]] == PETER_DIFFERENT
    assert peter["differing_fields"] == PETER_DIFFERENT


def test_any_member_ticket_opens_the_same_possible_duplicate(app):
    assert evidence(app, 855) == evidence(app, 620)


STRICT_FIELDS = [
    "Employee", "Date", "Job Number", "Time", "Regular Hours", "Overtime", "Double Time", "Job Work Pay",
]


def test_the_reason_and_every_candidate_edge_show_its_rule_fields_compared_and_evidence_strength(app):
    peter = evidence(app, 620)

    assert peter["reason"].startswith("Same claim submitted twice")
    assert "Peter Holder" in peter["reason"]
    assert [
        (c["excel_rows"], c["rule_id"], c["rule_label"], c["fields_compared"], c["evidence_strength"])
        for c in peter["candidates"]
    ] == [([620, 855], "strict_repeat", "Strict repeat", STRICT_FIELDS, "strong")]
    assert peter["candidates"][0]["reason"].startswith("Same claim submitted twice")
    assert peter["pattern_labels"] == ["Same claim appears twice"]
    assert peter["tier"]["rank"] == 1
    assert peter["exact_repeat_not_flagged"] is True


def test_the_timeline_lists_members_by_created_with_date_created_modified_date_approved_and_supervisor(app):
    timeline = evidence(app, 620)["timeline"]

    assert timeline["fields"] == ["Date", "Created", "Modified", "Date Approved", "Supervisor"]
    # Report: 855 was created 28 Sep 18:21, four days before 620 on 2 Oct 18:56.
    assert [
        (entry["excel_row"], entry["ticket_number"], [cell["value"] for cell in entry["cells"]])
        for entry in timeline["entries"]
    ] == [
        (855, "L225526", ["2026-09-28T00:00:00", "2026-09-28T18:21:00", "2026-10-01T13:44:00", "2026-09-29T09:36:00", "Jamar O'Neal"]),
        (620, "L225761", ["2026-09-28T00:00:00", "2026-10-02T18:56:00", "2026-10-05T07:48:00", "2026-10-05T07:42:00", "Jamar O'Neal"]),
    ]


def test_each_member_carries_its_provenance(app):
    members = evidence(app, 620)["members"]

    assert [member["provenance"] for member in members] == [
        {"snapshot_fingerprint": HANDOFF_WORKBOOK_SHA256, "sheet": SHEET, "excel_row": 855, "dataframe_index": 853},
        {"snapshot_fingerprint": HANDOFF_WORKBOOK_SHA256, "sheet": SHEET, "excel_row": 620, "dataframe_index": 618},
    ]


def test_each_member_carries_its_time_parse_with_raw_text_confidence_and_parser_version(app):
    peter = evidence(app, 620)

    for member in peter["members"]:
        parse = member["time_parse"]
        assert parse["raw_time"] == {"raw_type": "str", "value": "7:30 am to 4:30 pm"}
        assert parse["status"] == "confident"
        assert [(p["confidence"], p["interval"], p["plausible_reading"]) for p in parse["periods"]] == [
            ("confident", {"start": "07:30", "end": "16:30"}, None)
        ]
        assert parse["parser_version"] == peter["versions"]["parser"]
    assert [c["time_comparison"]["result"] for c in peter["candidates"]] == ["overlap"]


def test_an_ambiguous_time_shows_its_plausible_reading_labelled_assumed(tmp_path):
    workbook = write_workbook(tmp_path / "ambiguous.xlsx", [
        ticket(1, Employee="Ann Smith", Time="730-430"),
        ticket(2, Employee="Ann Smith", Time="730-430"),
    ])

    with running(workbook, tmp_path) as booted:
        fingerprint = booted.get("/api/snapshot").json()["snapshot_fingerprint"]
        payload = evidence(booted, 2, fingerprint)

    parse = payload["members"][0]["time_parse"]
    assert parse["raw_time"]["value"] == "730-430"
    assert parse["status"] == "ambiguous"
    assert [(p["confidence"], p["plausible_reading"]) for p in parse["periods"]] == [
        ("ambiguous", {"start": "07:30", "end": "16:30", "assumed": True})
    ]
    assert payload["candidates"][0]["time_comparison"]["result"] == "ambiguous"
    assert payload["candidates"][0]["time_comparison"]["assumed"] is True


def test_the_status_breakdown_is_member_level_and_never_a_paid_or_unpaid_summary(app):
    # Rows 425/1191: the one Approved/Pending strict pair (ticket #6).
    mixed = evidence(app, 425)

    assert sorted((b["status"], b["keyed"], b["flagged_duplicate"], b["tickets"]) for b in mixed["status_breakdown"]) == [
        ("Approved", True, False, 1),
        ("Pending", False, False, 1),
    ]
    text = str(mixed).lower()
    assert "paid" not in text and "unpaid" not in text


# The evidence report's 14 examples and their "Exact source rows" (29 Tickets).
REPORT_EXAMPLE_ROWS = {
    "A": {591, 593}, "B": {33, 79}, "C": {620, 855}, "D": {974, 1868}, "E": {1309, 1656}, "F": {2206, 2351},
    "G": {82, 103}, "H": {829, 1072}, "I": {318, 1545, 999}, "J": {61, 105}, "K": {2188, 2187},
    "L": {2151, 2152}, "M": {1575, 2149}, "N": {1727, 1728},
}


def test_the_annotations_file_covers_the_29_example_tickets_by_ticket_number(app):
    response = app.get("/api/annotations")

    assert response.status_code == 200
    examples = response.json()["examples"]
    assert [example["letter"] for example in examples] == list("ABCDEFGHIJKLMN")
    # Each ticket number resolves to the Excel row the report printed it on.
    assert {
        example["letter"]: {ticket["excel_row"] for ticket in example["tickets"]} for example in examples
    } == REPORT_EXAMPLE_ROWS
    assert sum(len(example["tickets"]) for example in examples) == 29
    assert all(example["questions_for_oliver"] for example in examples)
    # E and F have no "My review notes" in the report; every other example has one.
    assert [example["letter"] for example in examples if example["review_note"] is None] == ["E", "F"]


def test_the_peter_holder_possible_duplicate_carries_annotation_c_with_its_note_and_questions(app):
    annotations = evidence(app, 620)["annotations"]

    assert [annotation["letter"] for annotation in annotations] == ["C"]
    c = annotations[0]
    assert c["title"] == "Peter Holder: priority example"
    # Reworded from the report so no banned phrase reaches a screen; the section names where the original stays.
    assert c["review_note"].startswith("This looks like the strongest example of a repeat claim that was not flagged")
    assert "ask Oliver whether it was handled somewhere we cannot see" in c["review_note"]
    assert c["review_note_reworded"] is True
    assert c["source_section"] == "Pattern 1: The same claim appears twice > C. Peter Holder: priority example"
    assert c["questions_for_oliver"] == [
        "Were these caught or missed? If caught, where is that decision recorded when both retain nonzero job numbers?",
        "For Peter’s pair, show which ticket was retained and trace both through accounting and payment. "
        "Were both paid, or was one excluded elsewhere?",
    ]
    assert sorted((t["ticket_number"], t["excel_row"], t["in_possible_duplicate"]) for t in c["tickets"]) == [
        ("L225526", 855, True),
        ("L225761", 620, True),
    ]


BANNED_PHRASES = ("paid twice", "missed duplicate", "fraud")


def strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in strings(item)]
    if isinstance(value, list):
        return [text for item in value for text in strings(item)]
    return []


def test_no_annotation_text_uses_a_banned_phrase(app):
    texts = [text.casefold() for text in strings(app.get("/api/annotations").json()["examples"])]

    assert texts
    assert [text for text in texts if any(phrase in text for phrase in BANNED_PHRASES)] == []


def test_a_possible_duplicate_with_no_annotated_ticket_carries_no_annotation(app):
    assert evidence(app, 425)["annotations"] == []


def test_annotations_attach_by_ticket_number_and_never_create_a_possible_duplicate(tmp_path):
    # A Snapshot whose Ticket Numbers are C's but whose claims differ: no rule matches, so no drawer.
    workbook = write_workbook(tmp_path / "annotated.xlsx", [
        ticket(1, Employee="Ann Smith", Ticket_Number="L225761"),
        ticket(2, Employee="Bob Jones", Ticket_Number="L225526"),
        ticket(3, Employee="Cy Lee", Ticket_Number="L000003"),
        ticket(4, Employee="Cy Lee", Ticket_Number="L225790"),
    ])

    with running(workbook, tmp_path) as booted:
        fingerprint = booted.get("/api/snapshot").json()["snapshot_fingerprint"]
        found = booted.get("/api/review-priorities").json()["possible_duplicates"]
        unmatched = booted.get(f"/api/snapshots/{fingerprint}/tickets/2/possible-duplicate")
        cy = evidence(booted, 4, fingerprint)

    assert [item["display_id"] for item in found] == ["Possible duplicate L000003+L225790"]
    assert unmatched.status_code == 404
    assert [(a["letter"], [(t["ticket_number"], t["in_possible_duplicate"]) for t in a["tickets"]]) for a in cy["annotations"]] == [
        ("A", [("L225788", False), ("L225790", True)]),
    ]


def test_markup_whitespace_and_line_breaks_come_back_verbatim(tmp_path):
    markup = '<b>bold</b> <img src=x onerror="alert(1)">\n  second line  '
    workbook = write_workbook(tmp_path / "markup.xlsx", [
        ticket(1, Employee="Ann Smith", Description_of_Job_Work=markup, Job_Name="Sandals"),
        ticket(2, Employee="Ann Smith", Description_of_Job_Work=markup, Job_Name="Sandals "),
    ])

    with running(workbook, tmp_path) as booted:
        fingerprint = booted.get("/api/snapshot").json()["snapshot_fingerprint"]
        payload = evidence(booted, 2, fingerprint)

    assert column(payload, 2)["Description of Job Work"] == ("str", markup)
    assert column(payload, 3)["Job Name"] == ("str", "Sandals ")
    # A trailing space is a difference, as H's "Sandals" / "Sandals " is in the report.
    assert payload["differing_fields"] == ["Ticket Number", "Job Name", "ID", "Email Address"]


def test_blank_zero_and_false_stay_distinguishable_and_differ(tmp_path):
    workbook = write_workbook(tmp_path / "kinds.xlsx", [
        ticket(1, Employee="Ann Smith", Rate=None, Description_of_Job_Work=0, Keyed=False),
        ticket(2, Employee="Ann Smith", Rate=0, Description_of_Job_Work="0", Keyed=False),
    ])

    with running(workbook, tmp_path) as booted:
        fingerprint = booted.get("/api/snapshot").json()["snapshot_fingerprint"]
        payload = evidence(booted, 2, fingerprint)

    first, second = column(payload, 2), column(payload, 3)
    assert (first["Rate"], second["Rate"]) == (("blank", None), ("int", 0))
    assert (first["Description of Job Work"], second["Description of Job Work"]) == (("int", 0), ("str", "0"))
    assert first["Keyed"] == second["Keyed"] == ("bool", False)
    assert {"Rate", "Description of Job Work"} <= set(payload["differing_fields"])
    assert "Keyed" not in payload["differing_fields"]


def test_a_ticket_in_no_possible_duplicate_or_an_unknown_ticket_is_not_found(app):
    base = f"/api/snapshots/{HANDOFF_WORKBOOK_SHA256}/tickets"

    assert app.get(f"{base}/3/possible-duplicate").status_code == 404
    assert app.get(f"{base}/2838/possible-duplicate").status_code == 404
    assert app.get(f"/api/snapshots/{'0' * 64}/tickets/620/possible-duplicate").status_code == 404
