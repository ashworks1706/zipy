"""Fitting replies into a platform's message limit."""

from __future__ import annotations


def split(text: str, limit: int) -> list[str]:
    """The text in pieces of at most limit characters, broken at newlines where possible."""
    pieces: list[str] = []
    rest = text
    while len(rest) > limit:
        cut = rest.rfind("\n", 0, limit + 1)
        if cut <= 0:
            cut = limit
        pieces.append(rest[:cut])
        rest = rest[cut:].lstrip("\n")
    if rest:
        pieces.append(rest)
    return pieces
