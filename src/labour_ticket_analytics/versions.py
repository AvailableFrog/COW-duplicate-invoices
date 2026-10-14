"""The versions every numeric response carries, so a number can be traced to the code that made it.

The matching rules and the interval parser are not built yet; their tickets
(#5 and #6) raise these from 0.0.0 when they first produce results, and any
later change to a rule or to the parser bumps them again.
"""

from __future__ import annotations

from labour_ticket_analytics import __version__
from labour_ticket_analytics.metrics import REGISTRY_VERSION

RULE_VERSION = "0.0.0"
PARSER_VERSION = "0.0.0"


def versions() -> dict[str, str]:
    return {"app": __version__, "registry": REGISTRY_VERSION, "rules": RULE_VERSION, "parser": PARSER_VERSION}
