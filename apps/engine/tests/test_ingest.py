"""Chunking text and storing a document as embedded chunks."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from engine.core.config import Memory
from engine.core.doubles import FixedEmbedder, MemoryDocuments
from engine.core.types import Document, IngestError, OrgId
from engine.memory.ingest.chunking import split, tokens
from engine.memory.ingest.pipeline import ingest

ORG = OrgId("org-1")
UPDATED = datetime(2026, 9, 1, tzinfo=UTC)


@dataclass
class RecordingEmbedder:
    """Embeds every text as one vector and keeps what it was asked to embed."""

    seen: list[list[str]] = field(default_factory=list)
    short: bool = False

    async def embed(self, org_id: OrgId, texts: Sequence[str]) -> list[list[float]]:
        self.seen.append(list(texts))
        vectors = [[float(len(text))] for text in texts]
        return vectors[:-1] if self.short else vectors


def words(count: int) -> str:
    """A text of count distinct words."""
    return " ".join(f"w{index:03d}" for index in range(count))


def document(text: str, source_id: str = "d1") -> Document:
    """One document of a syncing tool."""
    return Document(
        source="drive",
        source_id=source_id,
        title="Budget notes",
        text=text,
        updated_at=UPDATED,
        metadata={"owner": "treasurer"},
    )


# ---------------------------------------------------------------- chunking


def test_chunks_hold_the_configured_size_and_overlap():
    memory = Memory(chunk_tokens=10, chunk_overlap_tokens=3)
    chunks = split(words(25), memory)
    assert [len(tokens(chunk)) for chunk in chunks] == [10, 10, 10, 4]
    for earlier, later in zip(chunks, chunks[1:], strict=False):
        assert tokens(earlier)[-3:] == tokens(later)[:3], "each chunk overlaps the last by three"
    assert tokens(chunks[0])[0] == "w000"
    assert tokens(chunks[-1])[-1] == "w024"


def test_every_word_of_the_text_reaches_a_chunk():
    memory = Memory(chunk_tokens=8, chunk_overlap_tokens=2)
    covered: list[str] = []
    for chunk in split(words(30), memory):
        for word in tokens(chunk):
            if word not in covered:
                covered.append(word)
    assert covered == tokens(words(30))


def test_a_text_shorter_than_one_chunk_is_one_chunk():
    assert split(words(4), Memory(chunk_tokens=10, chunk_overlap_tokens=3)) == [words(4)]


def test_a_tail_that_only_repeats_the_overlap_is_dropped():
    memory = Memory(chunk_tokens=10, chunk_overlap_tokens=4)
    chunks = split(words(13), memory)
    assert len(chunks) == 2
    assert tokens(chunks[-1])[-1] == "w012", "the tail is still covered by the last chunk"


def test_no_overlap_gives_consecutive_chunks():
    every = tokens(words(9))
    chunks = split(words(9), Memory(chunk_tokens=3, chunk_overlap_tokens=0))
    assert chunks == [" ".join(every[start : start + 3]) for start in (0, 3, 6)]


def test_empty_text_is_no_chunks():
    assert split("   \n ", Memory()) == []


# ---------------------------------------------------------------- the pipeline


async def test_a_document_is_stored_as_chunks_the_embedder_saw():
    memory = Memory(chunk_tokens=10, chunk_overlap_tokens=2)
    store = MemoryDocuments()
    embedder = RecordingEmbedder()
    stored = await ingest(ORG, document(words(25)), memory, embedder, store)
    assert stored == len(store.chunks) == 3
    assert embedder.seen == [[chunk.text for chunk in store.chunks]]
    assert [chunk.index for chunk in store.chunks] == [0, 1, 2]
    assert {chunk.source for chunk in store.chunks} == {"drive"}
    assert {chunk.org_id for chunk in store.chunks} == {ORG}
    assert store.chunks[0].title == "Budget notes"
    assert store.chunks[0].metadata["owner"] == "treasurer"
    assert store.chunks[0].metadata["updated_at"] == UPDATED.isoformat()


async def test_a_second_ingest_replaces_the_chunks_the_document_had():
    memory = Memory(chunk_tokens=10, chunk_overlap_tokens=2)
    store = MemoryDocuments()
    await ingest(ORG, document(words(25)), memory, FixedEmbedder([0.1]), store)
    await ingest(ORG, document("one short line"), memory, FixedEmbedder([0.1]), store)
    assert [chunk.text for chunk in store.chunks] == ["one short line"]


async def test_another_org_keeps_its_own_chunks_for_the_same_document():
    memory = Memory(chunk_tokens=10, chunk_overlap_tokens=2)
    store = MemoryDocuments()
    await ingest(ORG, document("first org text"), memory, FixedEmbedder([0.1]), store)
    await ingest(OrgId("org-2"), document("second org text"), memory, FixedEmbedder([0.1]), store)
    assert {chunk.org_id for chunk in store.chunks} == {ORG, OrgId("org-2")}


async def test_an_emptied_document_drops_its_chunks_and_embeds_nothing():
    memory = Memory(chunk_tokens=10, chunk_overlap_tokens=2)
    store = MemoryDocuments()
    embedder = RecordingEmbedder()
    await ingest(ORG, document(words(25)), memory, embedder, store)
    stored = await ingest(ORG, document(""), memory, embedder, store)
    assert stored == 0
    assert store.chunks == []
    assert len(embedder.seen) == 1, "an empty document costs no embedding call"


async def test_an_embedder_that_returns_too_few_vectors_is_an_error():
    store = MemoryDocuments()
    with pytest.raises(IngestError, match="vectors"):
        await ingest(
            ORG,
            document(words(25)),
            Memory(chunk_tokens=10, chunk_overlap_tokens=2),
            RecordingEmbedder(short=True),
            store,
        )
    assert store.chunks == [], "nothing is stored when the embedding does not line up"


async def test_a_document_without_a_source_id_is_an_error():
    with pytest.raises(IngestError, match="source_id"):
        await ingest(
            ORG, document("text", source_id=""), Memory(), FixedEmbedder([0.1]), MemoryDocuments()
        )
