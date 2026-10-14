"""Ticket #2: a Ticket fetched by Snapshot and Excel row returns every cell verbatim."""

from conftest import HANDOFF_WORKBOOK_SHA256


def ticket(app, excel_row: int, fingerprint: str = HANDOFF_WORKBOOK_SHA256):
    return app.get(f"/api/snapshots/{fingerprint}/tickets/{excel_row}")


def cells_by_field(payload: dict) -> dict[str, dict]:
    return {cell["field"]: cell for cell in payload["cells"]}


def test_peter_holder_row_620_returns_all_22_fields_as_the_evidence_report_prints_them(app):
    # Expected values are the "Exact source rows: 620 / 855" table in
    # docs/source/labour-ticket-report-readable.md (C. Peter Holder).
    response = ticket(app, 620)

    assert response.status_code == 200
    payload = response.json()
    assert payload["excel_row"] == 620
    assert payload["dataframe_index"] == 618
    assert payload["sheet"] == "Labour Tickets (1)"
    assert payload["snapshot_fingerprint"] == HANDOFF_WORKBOOK_SHA256
    assert [(c["field"], c["raw_type"], c["value"]) for c in payload["cells"]] == [
        ("Employee", "str", "Peter Holder"),
        ("Occupation", "str", "Labourer"),
        ("Ticket Number", "str", "L225761"),
        ("Job Name", "str", "Beachlands"),
        ("Job Number", "int", 41215),
        ("Date", "datetime", "2026-09-28T00:00:00"),
        ("Time", "str", "7:30 am to 4:30 pm"),
        ("Regular Hours", "int", 8),
        ("Overtime", "int", 0),
        ("Double Time", "int", 0),
        ("Job Work Pay", "int", 0),
        ("Description of Job Work", "str", "None"),
        ("Supervisor", "str", "Jamar O'Neal"),
        ("Approval Status", "str", "Approved"),
        ("Modified", "datetime", "2026-10-05T07:48:00"),
        ("Created", "datetime", "2026-10-02T18:56:00"),
        ("ID", "int", 224761),
        ("Email Address", "str", "Nardyspringer@gmail.com"),
        ("Keyed", "bool", True),
        ("Rate", "float", 14.53),
        ("Date Approved", "datetime", "2026-10-05T07:42:00"),
        ("Modified By", "str", "Tracy Whitehall"),
    ]


def test_blank_zero_and_false_stay_distinguishable(app):
    # Excel row 3 (Sanjay Lynch, L226378) has a numeric zero in Time, an empty
    # Rate and Keyed false, and a description with line breaks and a double space.
    payload = ticket(app, 3).json()

    cells = cells_by_field(payload)
    assert cells["Ticket Number"]["value"] == "L226378"
    assert cells["Time"] == {"field": "Time", "position": 6, "raw_type": "int", "value": 0, "number_format": "General"}
    assert cells["Rate"]["raw_type"] == "blank"
    assert cells["Rate"]["value"] is None
    assert cells["Keyed"]["raw_type"] == "bool"
    assert cells["Keyed"]["value"] is False
    assert cells["Job Work Pay"]["value"] == 0
    assert cells["Description of Job Work"]["value"] == (
        "Vacation from \n2026-10-16 to 2026-11-05 \nReturning  to work 2026-11-06"
    )


def test_typed_time_cells_keep_their_raw_type(app):
    # Excel row 56 has a datetime in Time and row 76 a float (verified observation
    # 20 in docs/decision-log.md: 132 int, 4 float, 2 datetime Time cells).
    assert cells_by_field(ticket(app, 56).json())["Time"]["value"] == "2026-12-30T07:30:00"
    assert cells_by_field(ticket(app, 56).json())["Time"]["raw_type"] == "datetime"
    assert cells_by_field(ticket(app, 76).json())["Time"] == {
        "field": "Time", "position": 6, "raw_type": "float", "value": 730.43, "number_format": "General",
    }


def test_unknown_excel_row_or_snapshot_is_not_found(app):
    assert ticket(app, 1).status_code == 404  # the header row is not a Ticket
    assert ticket(app, 2838).status_code == 404  # past the last data row
    assert ticket(app, 620, fingerprint="0" * 64).status_code == 404
