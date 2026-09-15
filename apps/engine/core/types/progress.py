"""Live progress: one displayable line per trace event, and how much detail it carries.

The engine renders the text; a platform displays what it is given and never keeps its own copy
of the event names. A line carrying a slot replaces the earlier line in that slot, so a tool
result writes over the line that said the tool had started.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: Characters of a tool argument list or a result one line carries.
DETAIL_CHARS = 160

#: Characters of reasoning a thinking line carries.
THOUGHT_CHARS = 600


@dataclass(frozen=True)
class ProgressStyle:
    """How much of a call, a result or a thought one line shows."""

    detail_chars: int = DETAIL_CHARS
    thought_chars: int = THOUGHT_CHARS


@dataclass(frozen=True)
class Progress:
    """One line of progress for a watcher."""

    #: Name of the trace event this came from.
    event: str
    #: Ready-to-display sentence.
    text: str
    #: The line this replaces, when it replaces one.
    slot: str | None = None
    #: Removes the line of slot instead of writing text there.
    clear: bool = False
    #: The text is the answer so far, not a step.
    draft: bool = False


def one_line(text: str) -> str:
    """The text as a single line, runs of whitespace collapsed."""
    return " ".join(str(text).split())


def clip(text: str, most: int) -> str:
    """The text cut to most characters, ending in an ellipsis when cut."""
    if most <= 0:
        return ""
    if len(text) <= most:
        return text
    if most < 3:
        return text[:most]
    return text[: most - 3].rstrip() + "..."


def plural(count: int, one: str, many: str) -> str:
    """one when count is 1, many otherwise."""
    return one if count == 1 else many


def call_arguments(arguments: Any, most: int) -> str:
    """The arguments of a call, rendered for a line. Empty when there are none."""
    if not isinstance(arguments, dict) or not arguments:
        return ""
    pairs = ", ".join(f"{name}={one_line(str(value))}" for name, value in arguments.items())
    return f" ({clip(pairs, most)})"


def progress(name: str, data: dict[str, Any], style: ProgressStyle) -> Progress | None:
    """The line for one trace event, or None when the event is bookkeeping."""
    detail = style.detail_chars
    if name == "model_started":
        return Progress(event=name, text="\U0001f914 thinking", slot="model")
    if name == "generation":
        return _generation(name, data, style)
    if name == "tool_started":
        action = data.get("action", "")
        return Progress(
            event=name,
            text=f"\U0001f527 `{action}`{call_arguments(data.get('arguments'), detail)} — running",
            slot=f"tool:{data.get('id', action)}",
        )
    if name == "tool_call":
        return _tool_call(name, data, style)
    if name == "recall":
        count = int(data.get("count", 0) or 0)
        if count == 0:
            return None
        return Progress(
            event=name,
            text=f"\U0001f9e0 reading {count} {plural(count, 'note', 'notes')} from before",
        )
    if name == "confirmation" and data.get("answer") is None:
        return Progress(event=name, text="✋ this one needs your approval")
    if name == "model_error" and data.get("retryable"):
        return Progress(event=name, text="\U0001f504 the model stumbled, retrying", slot="model")
    if name == "answer_draft":
        draft = str(data.get("text", "")).strip()
        if not draft:
            return None
        return Progress(event=name, text=draft, slot="answer", draft=True)
    if name == "reply":
        return Progress(event=name, text="", slot="model", clear=True)
    return None


def _generation(name: str, data: dict[str, Any], style: ProgressStyle) -> Progress | None:
    """A finished model call: what it decided, over the thinking line."""
    calls = data.get("tool_calls") or []
    if calls:
        named = ", ".join(f"`{one_line(str(call))}`" for call in calls)
        return Progress(event=name, text=f"\U0001f4ad calling {named}", slot="model")
    thought = clip(one_line(str(data.get("output", ""))), style.thought_chars)
    if not thought:
        return None
    return Progress(event=name, text=f"\U0001f4ad {thought}", slot="model")


def _tool_call(name: str, data: dict[str, Any], style: ProgressStyle) -> Progress:
    """A finished tool call, over the line that said it had started."""
    detail = style.detail_chars
    action = data.get("action", "")
    head = f"`{action}`"
    slot = f"tool:{data.get('id', action)}"
    if data.get("ok"):
        shown = clip(one_line(str(data.get("target", ""))), detail)
        text = f"✅ {head} → {shown}" if shown else f"✅ {head} — done"
        return Progress(event=name, text=text, slot=slot)
    error = clip(one_line(str(data.get("error", ""))), detail)
    return Progress(event=name, text=f"❌ {head} — {error}", slot=slot)
