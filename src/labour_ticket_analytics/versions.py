"""The versions every numeric response carries, so a number can be traced to the code that made it.

The matching rules are not built yet; their ticket (#6) raises the rule
version from 0.0.0 when they first produce results. Any later change to a rule
or to the interval parser bumps its version again.
"""

from __future__ import annotations

from labour_ticket_analytics import __version__
from labour_ticket_analytics.metrics import REGISTRY_VERSION
from labour_ticket_analytics.timeparse import PARSER_VERSION

RULE_VERSION = "0.0.0"


def versions() -> dict[str, str]:
    return {"app": __version__, "registry": REGISTRY_VERSION, "rules": RULE_VERSION, "parser": PARSER_VERSION}
