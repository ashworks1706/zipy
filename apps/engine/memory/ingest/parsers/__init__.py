"""One parser per media type, and the registry that picks between them.

A parser takes bytes and a limit in characters and returns text. It never fetches anything, never
runs what it reads, and stops at the limit rather than returning a document nothing can hold.
"""

from __future__ import annotations

from collections.abc import Callable

from engine.core.types import FILE_MEDIA_TYPES
from engine.memory.ingest.parsers import archive, office, pdf, text

#: Media type to the parser that reads it.
PARSERS: dict[str, Callable[[bytes, int], str]] = {
    "text/plain": text.read,
    "text/markdown": text.read,
    "text/csv": text.read,
    "application/json": text.read,
    "application/pdf": pdf.read,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": office.read_docx,
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": office.read_pptx,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": office.read_xlsx,
    "application/zip": archive.read,
    "application/x-zip-compressed": archive.read,
}


def parser_for(media_type: str) -> Callable[[bytes, int], str] | None:
    """The parser for a media type, or None when nothing reads it."""
    return PARSERS.get(media_type)


def unhandled() -> tuple[str, ...]:
    """Every media type the types module offers that no parser reads."""
    return tuple(kind for kind in FILE_MEDIA_TYPES if kind not in PARSERS)
