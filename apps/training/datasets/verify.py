"""Keeping only the examples worth judging: well-formed, not empty, not duplicates."""

from __future__ import annotations

import hashlib
import json

from training.core.types import TrainingExample


def fingerprint(example: TrainingExample) -> str:
    """What an example is, as a hash of what would be trained on."""
    payload = json.dumps(
        {"m": example.messages, "r": example.reply, "t": example.tool_calls},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def reject_reason(example: TrainingExample) -> str | None:
    """Why an example cannot be trained on, or None."""
    if not example.messages:
        return "no messages"
    roles = [message.get("role") for message in example.messages]
    if roles[0] != "system":
        return "first message is not system"
    if "user" not in roles:
        return "no user turn"
    if not example.reply.strip() and not example.tool_calls:
        return "empty reply"
    for call in example.tool_calls:
        function = call.get("function") or {}
        if not function.get("name"):
            return "tool call without a name"
    return None


def verify(examples: list[TrainingExample]) -> tuple[list[TrainingExample], dict[str, int]]:
    """The examples worth judging, and a count of each reason the rest were dropped."""
    kept: list[TrainingExample] = []
    reasons: dict[str, int] = {}
    seen: set[str] = set()
    for example in examples:
        reason = reject_reason(example)
        if reason is None:
            mark = fingerprint(example)
            if mark in seen:
                reason = "duplicate"
            else:
                seen.add(mark)
        if reason:
            reasons[reason] = reasons.get(reason, 0) + 1
            continue
        kept.append(example)
    return kept, reasons
