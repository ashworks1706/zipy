"""Splitting text into overlapping chunks of about chunk_tokens tokens.

A token here is one whitespace-separated word, which needs no tokenizer and no model call. The
chunks are what the embedder sees, so a change of unit changes what is stored.
"""

from __future__ import annotations

from engine.core.config import Memory


def tokens(text: str) -> list[str]:
    """The text as the tokens chunking counts."""
    return text.split()


def split(text: str, memory: Memory) -> list[str]:
    """Chunks of at most chunk_tokens, each overlapping the last by chunk_overlap_tokens."""
    words = tokens(text)
    if not words:
        return []
    size = memory.chunk_tokens
    stride = size - memory.chunk_overlap_tokens
    chunks = [" ".join(words[start : start + size]) for start in range(0, len(words), stride)]
    while len(chunks) > 1 and len(tokens(chunks[-1])) <= memory.chunk_overlap_tokens:
        chunks.pop()
    return chunks
