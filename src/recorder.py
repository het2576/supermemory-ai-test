"""Records every HTTP exchange so any claim in a report can be traced to raw evidence.

Headers are never stored, so the API key cannot end up in an evidence file. scrub() is a second,
defensive pass over anything about to be written to disk.
"""

from __future__ import annotations

import json
from typing import Any


class Recorder:
    def __init__(self) -> None:
        self._log: list[dict[str, Any]] = []

    def push(self, exchange: dict[str, Any]) -> None:
        self._log.append(exchange)

    @property
    def last(self) -> dict[str, Any] | None:
        return self._log[-1] if self._log else None

    def drain(self) -> list[dict[str, Any]]:
        out, self._log = self._log, []
        return out


def scrub(value: Any, secrets: list[str]) -> Any:
    """Replace any occurrence of a secret (len >= 8) in the JSON form of value."""
    live = [s for s in secrets if s and len(s) >= 8]
    if not live:
        return value
    text = json.dumps(value, default=str)
    for s in live:
        text = text.replace(s, "[REDACTED]")
    return json.loads(text)
