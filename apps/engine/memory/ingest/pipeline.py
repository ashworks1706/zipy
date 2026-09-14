"""Chunk, embed and store one document, replacing the chunks it had before."""

from __future__ import annotations

from engine.core.config import Memory
from engine.core.protocols import DocumentStore, Embedder
from engine.core.types import Document, OrgId


async def ingest(
    org_id: OrgId,
    document: Document,
    memory: Memory,
    embedder: Embedder,
    documents: DocumentStore,
) -> int:
    """Store the document as chunks. Returns how many."""
    raise NotImplementedError
