"""The JSON lines zipy chat --jsonl speaks, one object per line.

In, on stdin: {"op": "ask", "text": ...}, {"op": "confirm", "approve": true|false},
{"op": "new"} to start a new conversation, {"op": "stats"} for the metrics snapshot.

Out, on stdout: {"type": "ready"}, {"type": "event", "event": {...}} per trace event,
{"type": "result", "result": {...}} per reply, {"type": "stats", "stats": {...}},
{"type": "error", "message": ...}.

The console parses these on its own side; it never imports this module.
"""

from __future__ import annotations

import json
from typing import Any, Literal

Op = Literal["ask", "confirm", "new", "stats"]
OPS: tuple[Op, ...] = ("ask", "confirm", "new", "stats")


def decode(line: str) -> dict[str, Any] | None:
    """One inbound message with a known op, or None."""
    try:
        message = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(message, dict) or message.get("op") not in OPS:
        return None
    return message


def encode(kind: str, **fields: Any) -> str:
    """One outbound line."""
    return json.dumps({"type": kind, **fields}, default=str)
