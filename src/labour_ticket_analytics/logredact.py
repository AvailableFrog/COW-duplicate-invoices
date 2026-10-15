"""Keep source data out of the service's logs.

The service logs only at warning level and never logs requests, so in normal
running it prints nothing but its start-up lines, which carry counts and
identifiers, never cell values. The one remaining route for data into a log
is an unexpected exception: its message can quote a value (a KeyError on an
employee name, say). This filter keeps the exception type and where it was
raised, which is what diagnosing it needs, and drops the message.
"""

from __future__ import annotations

import logging
import traceback

REDACTED = "[message withheld: it may quote source data]"
LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.asgi", "labour_ticket_analytics")


class WithholdExceptionMessages(logging.Filter):
    """Replace a record's exception with its type and frames, without the message."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info and record.exc_info[1] is not None:
            kind, error, trace = record.exc_info
            frames = "".join(traceback.format_tb(trace))
            name = kind.__qualname__ if kind is not None else type(error).__qualname__
            record.exc_text = f"Traceback (most recent call last):\n{frames}{name}: {REDACTED}"
            record.exc_info = None
        return True


def install() -> None:
    """Attach the filter to the service's loggers and their handlers."""
    withhold = WithholdExceptionMessages()
    for name in LOGGERS:
        logger = logging.getLogger(name)
        logger.addFilter(withhold)
        for handler in logger.handlers:
            handler.addFilter(withhold)
