"""Chunk, embed and store one document, replacing the chunks it had before."""

from __future__ import annotations

from engine.core.config import Memory
from engine.core.protocols import DocumentStore, Embedder
from engine.core.types import Chunk, Document, IngestError, OrgId
from engine.memory.ingest.chunking import split


async def ingest(
    org_id: OrgId,
    document: Document,
    memory: Memory,
    embedder: Embedder,
    documents: DocumentStore,
) -> int:
    """Store the document as chunks. Returns how many."""
    if not document.source or not document.source_id:
        raise IngestError(f"a {document.source or 'document'} has no source or source_id")
    texts = split(document.text, memory)
    if not texts:
        await documents.replace(org_id, document.source, document.source_id, (), ())
        return 0
    embeddings = await embedder.embed(org_id, texts)
    if len(embeddings) != len(texts):
        raise IngestError(
            f"{document.source}:{document.source_id} has {len(texts)} chunks but the embedder "
            f"returned {len(embeddings)} vectors"
        )
    metadata = {**document.metadata, "updated_at": document.updated_at.isoformat()}
    chunks = [
        Chunk(
            org_id=org_id,
            source=document.source,
            source_id=document.source_id,
            index=index,
            title=document.title,
            text=text,
            metadata=dict(metadata),
        )
        for index, text in enumerate(texts)
    ]
    await documents.replace(org_id, document.source, document.source_id, chunks, embeddings)
    return len(chunks)
