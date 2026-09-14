"""Org facts as the text block the system prompt shows, grouped by category."""

from __future__ import annotations

from collections.abc import Sequence

from engine.core.types import FactCategory, OrgFact


def render(facts: Sequence[OrgFact]) -> str:
    """The facts under one heading per category, in FactCategory order. Empty when none."""
    blocks = []
    for category in FactCategory:
        lines = [f"- {f.key}: {f.value}" for f in facts if f.category is category]
        if lines:
            blocks.append(f"## {category.value}\n" + "\n".join(lines))
    return "\n\n".join(blocks)
