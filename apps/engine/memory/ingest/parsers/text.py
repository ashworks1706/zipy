"""Plain text, markdown, csv and json."""

from __future__ import annotations


def read(raw: bytes, limit: int) -> str:
    """The bytes as text, cut to the limit. Undecodable bytes become replacement characters."""
    return raw.decode("utf-8", "replace")[:limit]
