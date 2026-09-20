"""Removing what a training set must not carry.

The engine already keeps credentials out of a trace, so this is about the people in the messages:
an email address, a phone number, a platform id. A dataset outlives the conversation it came from.
"""

from __future__ import annotations

import re
from typing import Any

from testbed.core.types import TrainingExample

#: What is replaced, and what it is replaced by.
PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[email]"),
    (re.compile(r"(?<!\d)(?:\+?\d{1,2}[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}(?!\d)"), "[phone]"),
    (re.compile(r"<@!?\d{17,20}>"), "[mention]"),
    (re.compile(r"(?<!\d)\d{17,20}(?!\d)"), "[platform-id]"),
    (re.compile(r"\bxox[baprs]-[\w-]{10,}", re.I), "[token]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), "[token]"),
)


def redact_text(text: str) -> str:
    """One string with every pattern replaced."""
    for pattern, replacement in PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _value(value: Any) -> Any:
    """One JSON value, redacted wherever it is a string."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _value(item) for key, item in value.items()}
    return value


def redact(example: TrainingExample) -> TrainingExample:
    """One example with its messages, reply and tool call arguments redacted."""
    return example.model_copy(
        update={
            "messages": [_value(message) for message in example.messages],
            "reply": redact_text(example.reply),
            "tool_calls": [_value(call) for call in example.tool_calls],
        }
    )
