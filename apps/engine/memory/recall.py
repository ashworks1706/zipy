"""Semantic recall: embed the message, search the org's chunks, keep the close ones."""

from __future__ import annotations

from engine.core.config import Memory
from engine.core.protocols import DocumentStore, Embedder
from engine.core.types import IngestError, RecallHit, RequestContext


async def recall(
    ctx: RequestContext,
    message: str,
    memory: Memory,
    embedder: Embedder,
    documents: DocumentStore,
) -> list[RecallHit]:
    """The top recall_top_k chunks above recall_min_similarity for the message's org."""
    vectors = await embedder.embed(ctx.org_id, [message])
    if not vectors:
        raise IngestError("the embedder returned no vector for the message")
    return await documents.search(
        ctx.org_id,
        vectors[0],
        memory.recall_top_k,
        memory.recall_min_similarity,
    )
