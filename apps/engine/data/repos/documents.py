"""The documents table and its pgvector similarity search."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from engine.core.types import Chunk, OrgId, RecallHit, StoreError
from engine.data.db import org_uuid, store_errors
from engine.data.tables import DocumentRow


class PgDocuments:
    """The Postgres implementation of DocumentStore."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def replace(
        self,
        org_id: OrgId,
        source: str,
        source_id: str,
        chunks: Sequence[Chunk],
        embeddings: Sequence[Sequence[float]],
    ) -> None:
        """Swap every stored chunk of one document for these, in one transaction."""
        if len(chunks) != len(embeddings):
            raise StoreError(
                f"{source}/{source_id} has {len(chunks)} chunks and {len(embeddings)} embeddings"
            )
        foreign = [c for c in chunks if c.org_id != org_id]
        if foreign:
            raise StoreError(f"{source}/{source_id} holds chunks of another org")
        scope = org_uuid(org_id)
        ingested = datetime.now(UTC)
        rows = [
            DocumentRow(
                org_id=scope,
                source=source,
                source_id=source_id,
                chunk_index=chunk.index,
                title=chunk.title,
                text=chunk.text,
                meta=dict(chunk.metadata),
                embedding=list(embedding),
                source_updated_at=ingested,
            )
            for chunk, embedding in zip(chunks, embeddings, strict=True)
        ]
        async with store_errors("documents.replace"), self._sessions() as session, session.begin():
            await session.execute(
                delete(DocumentRow).where(
                    DocumentRow.org_id == scope,
                    DocumentRow.source == source,
                    DocumentRow.source_id == source_id,
                )
            )
            session.add_all(rows)

    async def search(
        self,
        org_id: OrgId,
        embedding: Sequence[float],
        top_k: int,
        min_similarity: float,
        sources: Sequence[str] = (),
    ) -> list[RecallHit]:
        """The closest chunks of this org, nearest first, none below min_similarity."""
        if top_k <= 0:
            return []
        distance = DocumentRow.embedding.cosine_distance(list(embedding))
        statement = (
            select(DocumentRow, distance)
            .where(DocumentRow.org_id == org_uuid(org_id), distance <= 1 - min_similarity)
            .order_by(distance)
            .limit(top_k)
        )
        if sources:
            statement = statement.where(DocumentRow.source.in_(list(sources)))
        async with store_errors("documents.search"), self._sessions() as session:
            found = (await session.execute(statement)).all()
            return [
                RecallHit(
                    chunk=Chunk(
                        org_id=OrgId(str(row.org_id)),
                        source=row.source,
                        source_id=row.source_id,
                        index=row.chunk_index,
                        title=row.title,
                        text=row.text,
                        metadata=dict(row.meta),
                    ),
                    similarity=1.0 - float(gap),
                )
                for row, gap in found
            ]

    async def prune(self, source: str, older_than: datetime) -> int:
        """Drop every chunk of that source older than the retention window, across every org."""
        statement = (
            delete(DocumentRow)
            .where(DocumentRow.source == source, DocumentRow.source_updated_at < older_than)
            .returning(DocumentRow.id)
        )
        async with store_errors("documents.prune"), self._sessions() as session, session.begin():
            dropped = (await session.scalars(statement)).all()
        return len(dropped)
