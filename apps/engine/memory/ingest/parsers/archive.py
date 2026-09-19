"""Zip archives, read one entry at a time.

A zip is the one type that can cost far more to read than it does to send, so every limit here is
about what comes out rather than what went in: how many entries, how large each is, and how large
they are together. A nested archive is named and not opened.
"""

from __future__ import annotations

import io
import zipfile

from engine.memory.ingest.parsers.errors import ParseError

#: Entries read before the rest are only listed.
MAX_ENTRIES = 50

#: What one entry may weigh unpacked.
MAX_ENTRY_BYTES = 5_000_000

#: What every entry together may weigh unpacked, whatever the archive claims to be.
MAX_TOTAL_BYTES = 20_000_000


def _skipped(name: str, why: str) -> str:
    """A line standing in for an entry that was not read."""
    return f"[{name}: {why}]"


def read(raw: bytes, limit: int) -> str:
    """The text entries of an archive, each under its name."""
    from engine.memory.ingest.parsers.registry import parser_for

    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except (zipfile.BadZipFile, OSError) as exc:
        raise ParseError(f"that archive could not be opened: {type(exc).__name__}") from exc
    parts: list[str] = []
    unpacked = 0
    with archive:
        for info in archive.infolist()[:MAX_ENTRIES]:
            if info.is_dir():
                continue
            name = info.filename
            if name.lower().endswith(".zip"):
                parts.append(_skipped(name, "a nested archive is listed, not opened"))
                continue
            if info.file_size > MAX_ENTRY_BYTES:
                parts.append(_skipped(name, f"{info.file_size} bytes unpacked, too large to read"))
                continue
            if unpacked + info.file_size > MAX_TOTAL_BYTES:
                parts.append(_skipped(name, "the archive unpacks to more than this reads"))
                break
            parser = parser_for(_media_type(name))
            if parser is None:
                parts.append(_skipped(name, "nothing here reads that kind of file"))
                continue
            try:
                entry = archive.read(info)
            except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
                parts.append(_skipped(name, f"could not be unpacked: {type(exc).__name__}"))
                continue
            unpacked += len(entry)
            parts.append(f"{name}\n{parser(entry, limit)}")
            if sum(len(p) for p in parts) >= limit:
                break
    return "\n\n".join(parts)[:limit]


#: File suffix to the media type it is read as. A suffix nothing knows is listed and skipped.
SUFFIXES = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".json": "application/json",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _media_type(name: str) -> str:
    """The media type an entry is read as, from its suffix."""
    lowered = name.lower()
    for suffix, kind in SUFFIXES.items():
        if lowered.endswith(suffix):
            return kind
    return ""
