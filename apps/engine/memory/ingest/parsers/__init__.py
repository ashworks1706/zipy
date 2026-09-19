"""One parser per media type, and the registry that picks between them."""

from __future__ import annotations

from engine.core.types import FILE_MEDIA_TYPES
from engine.memory.ingest.parsers.errors import ParseError
from engine.memory.ingest.parsers.registry import PARSERS, Parser, parser_for

__all__ = ["PARSERS", "ParseError", "Parser", "parser_for", "unhandled"]


def unhandled() -> tuple[str, ...]:
    """Every media type the types module offers that no parser reads."""
    return tuple(kind for kind in FILE_MEDIA_TYPES if kind not in PARSERS)
