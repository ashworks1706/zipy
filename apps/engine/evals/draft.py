"""A case drafted from what a real request did.

The trace says what was asked, which actions ran, and whether anything waited for a confirmation.
It does not say what the answer should have carried, which is what the reviewer adds.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from engine.core.types import ConfigError
from engine.evals.cases import Case

#: The trace event carrying the messages one model call was given.
GENERATION = "generation"

#: The trace event a completed tool action writes.
TOOL_CALL = "tool_call"

#: The trace event a confirmation writes, whatever the answer.
CONFIRMATION = "confirmation"


def events(path: Path) -> list[dict[str, Any]]:
    """Every event in one request's trace file, in order."""
    if not path.exists():
        raise ConfigError(f"no trace at {path}")
    found = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            found.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not found:
        raise ConfigError(f"the trace at {path} holds no events")
    return found


def find(directory: Path, request_id: str) -> Path:
    """The trace of one request, whichever org wrote it."""
    for path in directory.glob(f"*/{request_id}.jsonl"):
        return path
    raise ConfigError(f"no trace for request {request_id} under {directory}")


def _text(content: Any) -> str:
    """The text of one wire message, whether it is a string or a content array."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(part.get("text", "") for part in content if isinstance(part, dict))
    return ""


def asked(found: list[dict[str, Any]]) -> str:
    """The question the request was made of, from the first model call it made."""
    for event in found:
        if event.get("event") != GENERATION:
            continue
        messages = (event.get("data") or {}).get("input") or []
        users = [_text(m.get("content")) for m in messages if m.get("role") == "user"]
        if users:
            return users[-1]
    return ""


def actions(found: list[dict[str, Any]]) -> tuple[str, ...]:
    """Every action that ran, in order, without repeats."""
    ran: list[str] = []
    for event in found:
        if event.get("event") != TOOL_CALL:
            continue
        action = str((event.get("data") or {}).get("action") or "")
        if action and action not in ran:
            ran.append(action)
    return tuple(ran)


def waited(found: list[dict[str, Any]]) -> bool:
    """Whether anything stopped for a confirmation."""
    return any(event.get("event") == CONFIRMATION for event in found)


def draft(case_id: str, found: list[dict[str, Any]]) -> Case:
    """A case recording what the request did. A trace with no question is a ConfigError."""
    question = asked(found)
    if not question:
        raise ConfigError("the trace holds no user message, so there is no case to draft")
    return Case(id=case_id, ask=question, calls=actions(found), confirms=waited(found))


def as_toml(case: Case) -> str:
    """One case as the [[case]] table it is written as."""
    lines = ["[[case]]", f'id = "{case.id}"', f"ask = {json.dumps(case.ask)}"]
    if case.calls:
        lines.append("calls = [" + ", ".join(json.dumps(call) for call in case.calls) + "]")
    lines.append("contains = []")
    if case.confirms:
        lines.append("confirms = true")
    return "\n".join(lines) + "\n"
