"""Media type to the parser that reads it.

A parser takes bytes and a limit in characters and returns text. It never fetches anything, never
runs what it reads, and stops at the limit. Nothing here imports from engine: the sandbox image
carries this package and none of the rest.
"""

from __future__ import annotations

from collections.abc import Callable

from engine.memory.ingest.parsers import archive, office, pdf, text

Parser = Callable[[bytes, int], str]

#: Media type to the parser that reads it.
PARSERS: dict[str, Parser] = {
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


def parser_for(media_type: str) -> Parser | None:
    """The parser for a media type, or None when nothing reads it."""
    return PARSERS.get(media_type)
