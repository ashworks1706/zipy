"""The one error a parser raises.

The parsers run both in the engine and inside the sandbox image, which carries no engine code,
so nothing here imports from engine.
"""

from __future__ import annotations


class ParseError(Exception):
    """A file could not be read as the type it claimed to be."""
