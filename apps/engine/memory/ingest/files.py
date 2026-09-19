"""An attached file, downloaded and read into a Document.

The bytes are fetched once, read by the parser for their media type, and stored as a document of
source upload, so the same file answers this turn and every later question about it. Nothing here
runs what it reads.

With files.sandbox on, the parser runs inside a container instead of in this process, on the same
parser code. A sandbox that will not run is a file that is not read; nothing falls back to parsing
an untrusted file beside the org's credentials.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shlex
from datetime import UTC, datetime
from pathlib import Path

import httpx

from engine.core.config import Files
from engine.core.protocols import Sandbox
from engine.core.types import (
    Attachment,
    Document,
    IngestError,
    RequestContext,
    SandboxRequest,
)
from engine.memory.ingest.parsers import ParseError, parser_for

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


#: Where the extractor lives inside the sandbox image.
EXTRACTOR = "/opt/zipy/extract.py"

#: The session attached files are parsed in. One per member, reused across their uploads.
PARSE_SESSION = "files"


def _extracted(stdout: str, name: str) -> str:
    """The text the extractor printed. Anything else is an IngestError naming the file."""
    line = stdout.strip().splitlines()[-1] if stdout.strip() else ""
    try:
        answer = json.loads(line)
    except ValueError as exc:
        raise IngestError(f"{name} could not be read: the sandbox said nothing usable") from exc
    if not isinstance(answer, dict) or "text" not in answer:
        why = answer.get("error", "no reason") if isinstance(answer, dict) else "no reason"
        raise IngestError(f"{name} could not be read: {why}")
    return str(answer["text"])


async def _in_sandbox(
    ctx: RequestContext, attachment: Attachment, raw: bytes, limits: Files, sandbox: Sandbox
) -> str:
    """The file's text, read by the parsers inside a container."""
    name = attachment.name or attachment.media_type
    stored = f"upload-{source_id(raw)[:16]}{Path(name).suffix[:8]}"
    path = await sandbox.put(ctx, PARSE_SESSION, stored, raw)
    command = " ".join(
        shlex.quote(part)
        for part in ("python3", EXTRACTOR, path, attachment.media_type, str(limits.max_chars))
    )
    output = await sandbox.run(ctx, SandboxRequest(command=command, session=PARSE_SESSION))
    return _extracted(output.stdout, name)


async def read(
    attachment: Attachment,
    limits: Files,
    transport: httpx.AsyncBaseTransport | None = None,
    ctx: RequestContext | None = None,
    sandbox: Sandbox | None = None,
) -> Document:
    """One attachment as a document. A type nothing reads, or a parser failure, is an IngestError.

    Parsing runs in a worker thread under a deadline: a parser that will not finish is a request
    that ends rather than one that hangs.
    """
    parser = parser_for(attachment.media_type)
    if parser is None:
        raise IngestError(f"nothing here reads {attachment.media_type}")
    raw = await download(attachment, limits, transport)
    if limits.sandbox:
        if sandbox is None or ctx is None:
            raise IngestError("files.sandbox is on and no sandbox is wired; nothing was read")
        text = await _in_sandbox(ctx, attachment, raw, limits, sandbox)
        return _document(attachment, raw, text)
    try:
        text = await asyncio.wait_for(
            asyncio.to_thread(parser, raw, limits.max_chars), limits.parse_timeout_secs
        )
    except TimeoutError as exc:
        raise IngestError(
            f"{attachment.name or 'that file'} took longer than "
            f"{limits.parse_timeout_secs}s to read"
        ) from exc
    except ParseError as exc:
        raise IngestError(str(exc)) from exc
    return _document(attachment, raw, text)


def _document(attachment: Attachment, raw: bytes, text: str) -> Document:
    """One read file as the document that answers this turn and every later question."""
    name = attachment.name or attachment.media_type
    return Document(
        source=SOURCE,
        source_id=source_id(raw),
        title=name,
        text=text,
        updated_at=datetime.now(UTC),
        metadata={"name": name, "media_type": attachment.media_type, "bytes": len(raw)},
    )
