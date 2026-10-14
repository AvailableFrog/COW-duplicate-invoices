"""The versions every numeric response carries, so a number can be traced to the code that made it.

Any change to a metric, a matching rule or the interval parser bumps its
version, declared beside the code it versions.
"""

from __future__ import annotations

from labour_ticket_analytics import __version__
from labour_ticket_analytics.metrics import REGISTRY_VERSION
from labour_ticket_analytics.rules import RULE_VERSION
from labour_ticket_analytics.timeparse import PARSER_VERSION


def versions() -> dict[str, str]:
    return {"app": __version__, "registry": REGISTRY_VERSION, "rules": RULE_VERSION, "parser": PARSER_VERSION}
