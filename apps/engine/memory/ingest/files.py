"""An attached file, downloaded and read into a Document.

The bytes are fetched once, read by the parser for their media type, and stored as a document of
source upload, so the same file answers this turn and every later question about it. Nothing here
runs what it reads.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime

import httpx

from engine.core.config import Files
from engine.core.types import Attachment, Document, IngestError
from engine.memory.ingest.parsers import parser_for

#: The source every uploaded file is stored under.
SOURCE = "upload"


def source_id(raw: bytes) -> str:
    """What names this file in the document store. The same bytes are the same document."""
    return hashlib.sha256(raw).hexdigest()[:32]


async def download(
    attachment: Attachment, limits: Files, transport: httpx.AsyncBaseTransport | None = None
) -> bytes:
    """The bytes of an attachment. Anything over the cap is refused rather than cut."""
    if attachment.size and attachment.size > limits.max_bytes:
        raise IngestError(
            f"{attachment.name or 'that file'} is {attachment.size} bytes, over the "
            f"{limits.max_bytes} files.max_bytes allows"
        )
    try:
        async with httpx.AsyncClient(
            timeout=limits.download_timeout_secs, transport=transport
        ) as client:
            response = await client.get(attachment.url, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise IngestError(f"that file could not be fetched: {type(exc).__name__}") from exc
    if response.is_error:
        raise IngestError(f"that file could not be fetched: HTTP {response.status_code}")
    raw = response.content
    if len(raw) > limits.max_bytes:
        raise IngestError(
            f"{attachment.name or 'that file'} is {len(raw)} bytes, over the "
            f"{limits.max_bytes} files.max_bytes allows"
        )
    return raw


async def read(
    attachment: Attachment, limits: Files, transport: httpx.AsyncBaseTransport | None = None
) -> Document:
    """One attachment as a document. A type nothing reads, or a parser failure, is an IngestError.

    Parsing runs in a worker thread under a deadline: a parser that will not finish is a request
    that ends rather than one that hangs.
    """
    parser = parser_for(attachment.media_type)
    if parser is None:
        raise IngestError(f"nothing here reads {attachment.media_type}")
    raw = await download(attachment, limits, transport)
    try:
        text = await asyncio.wait_for(
            asyncio.to_thread(parser, raw, limits.max_chars), limits.parse_timeout_secs
        )
    except TimeoutError as exc:
        raise IngestError(
            f"{attachment.name or 'that file'} took longer than "
            f"{limits.parse_timeout_secs}s to read"
        ) from exc
    name = attachment.name or attachment.media_type
    return Document(
        source=SOURCE,
        source_id=source_id(raw),
        title=name,
        text=text,
        updated_at=datetime.now(UTC),
        metadata={"name": name, "media_type": attachment.media_type, "bytes": len(raw)},
    )
