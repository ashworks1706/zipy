"""Whether a message should run semantic recall."""

from __future__ import annotations

from collections.abc import Sequence


def wants_recall(message: str, triggers: Sequence[str]) -> bool:
    """True when the message contains a trigger phrase, ignoring case."""
    text = " ".join(message.lower().split())
    return any(trigger.lower() in text for trigger in triggers)
