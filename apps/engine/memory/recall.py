"""Semantic recall: embed the message, search the org's chunks, keep the close ones."""

from __future__ import annotations

from engine.core.config import Memory
from engine.core.protocols import DocumentStore, Embedder
from engine.core.types import RecallHit, RequestContext


async def recall(
    ctx: RequestContext,
    message: str,
    memory: Memory,
    embedder: Embedder,
    documents: DocumentStore,
) -> list[RecallHit]:
    """The top recall_top_k chunks above recall_min_similarity for the message's org."""
    raise NotImplementedError
