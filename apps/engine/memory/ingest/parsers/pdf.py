"""PDF, page by page."""

from __future__ import annotations

import io

from engine.memory.ingest.parsers.errors import ParseError

#: Pages read before the rest is left. A limit in characters alone would still walk every page.
MAX_PAGES = 500


def read(raw: bytes, limit: int) -> str:
    """The text of a PDF. A file that cannot be opened is an IngestError."""
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    try:
        reader = PdfReader(io.BytesIO(raw))
        parts: list[str] = []
        size = 0
        for page in reader.pages[:MAX_PAGES]:
            parts.append(page.extract_text() or "")
            size += len(parts[-1])
            if size >= limit:
                break
    except (PyPdfError, ValueError, OSError) as exc:
        raise ParseError(f"that PDF could not be read: {type(exc).__name__}") from exc
    return "\n\n".join(parts)[:limit]
