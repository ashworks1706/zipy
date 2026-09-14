"""Splitting text into overlapping chunks of about chunk_tokens tokens."""

from __future__ import annotations

from engine.core.config import Memory


def split(text: str, memory: Memory) -> list[str]:
    """Chunks of at most chunk_tokens, each overlapping the last by chunk_overlap_tokens."""
    raise NotImplementedError
