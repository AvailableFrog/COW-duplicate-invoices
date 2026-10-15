"""The Explore result cache (PRD section 7, decision-log entry 84).

An executed plan is kept by its key, the plan as validated with the
inherited and compiled filter state, within a scope: the Snapshot, the
as-of date, the registry, rule and parser versions, and the review
revision (every committed change to outcomes, links or Aliases). An
identical request inside the same scope reuses the result; a request in a
different scope discards every entry first, so a result made before an
as-of, review or Snapshot change is never served again, even if the change
is later undone. The cache lives in memory for one launch and holds at most
`capacity` results, least recently used first out.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from typing import Any, Callable, Hashable


class ResultCache:
    def __init__(self, capacity: int = 64) -> None:
        self.capacity = capacity
        self._entries: OrderedDict[str, Any] = OrderedDict()
        self._scope: Hashable | None = None
        self._lock = threading.Lock()

    @staticmethod
    def key(request: dict[str, Any]) -> str:
        """A stable key for a request: its canonical JSON, hashed."""
        canonical = json.dumps(request, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def get_or_compute(self, scope: Hashable, key: str, compute: Callable[[], Any]) -> tuple[Any, bool]:
        """The cached value for the key within the scope, or a newly computed one; and whether it was a hit."""
        with self._lock:
            if scope != self._scope:
                self._entries.clear()
                self._scope = scope
            if key in self._entries:
                self._entries.move_to_end(key)
                return self._entries[key], True
        value = compute()
        with self._lock:
            if scope == self._scope:
                self._entries[key] = value
                self._entries.move_to_end(key)
                while len(self._entries) > self.capacity:
                    self._entries.popitem(last=False)
        return value, False
