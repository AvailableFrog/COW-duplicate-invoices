"""Ticket #18: logs carry no employee names, emails or descriptions.

Every service the API tests boot has its output collected in
test-logs/pytest-service.log, and conftest fails the run if the checker finds
any value from the workbook there. These tests show the checker and the
service's exception filter actually work.
"""

import io
import logging

from log_check import leaks, sensitive_values

from labour_ticket_analytics import logredact


def test_the_checker_reads_names_emails_and_long_descriptions_from_the_workbook():
    values = sensitive_values()
    assert "peter holder" in values
    assert "mariocollymore" in values
    assert "nardyspringer@gmail.com" in values
    assert "working along with the excavator man digging to find the pipes so he can’t burst them" in values
    # Short descriptions would match ordinary words, so they are not treated as identifying.
    assert "none" not in values and "boxing" not in values


def test_the_checker_finds_a_planted_value_whatever_its_case_or_spacing_and_passes_clean_start_up_lines():
    assert leaks("lookup failed for PETER   holder at row 620") == ["peter holder"]
    assert leaks("sent to Nardyspringer@gmail.com") == ["nardyspringer@gmail.com"]
    start_up = (
        "Imported Labour Tickets Export.xlsx as Snapshot 36378ee04717: 2836 rows, 22 fields, 0 import issues, 1.20s\n"
        "Local review data: /tmp/lta-review-x/review.duckdb\nListening on http://127.0.0.1:40000\n"
    )
    assert leaks(start_up) == []


def test_an_exception_message_that_quotes_source_data_is_withheld_but_its_type_and_location_are_kept():
    logger = logging.getLogger("uvicorn.error")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger.addHandler(handler)
    try:
        logredact.install()
        # The key comes from data, as in the service, so the printed source line names no one.
        employee = " ".join(["Peter", "Holder"])
        try:
            {}[employee]
        except KeyError:
            logger.exception("Exception in ASGI application")
    finally:
        logger.removeHandler(handler)
        for name in logredact.LOGGERS:
            logging.getLogger(name).filters.clear()

    output = stream.getvalue()
    assert "Exception in ASGI application" in output
    assert "KeyError: [message withheld: it may quote source data]" in output
    assert "test_log_redaction.py" in output
    assert "Peter Holder" not in output
