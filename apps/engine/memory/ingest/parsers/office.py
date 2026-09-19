"""The Open XML formats: Word, PowerPoint and Excel."""

from __future__ import annotations

import io

from engine.memory.ingest.parsers.errors import ParseError

#: Slides, rows and paragraphs read before the rest is left.
MAX_PARTS = 5000


def _opened(raw: bytes, kind: str, open_it: object) -> object:
    """One document, or an IngestError naming the kind that would not open."""
    try:
        return open_it(io.BytesIO(raw))  # type: ignore[operator]
    except Exception as exc:  # noqa: BLE001 - the libraries raise their own unrelated types
        raise ParseError(f"that {kind} could not be read: {type(exc).__name__}") from exc


def read_docx(raw: bytes, limit: int) -> str:
    """The paragraphs of a Word document, in order."""
    from docx import Document as WordDocument

    document = _opened(raw, "Word document", WordDocument)
    parts = [p.text for p in document.paragraphs[:MAX_PARTS] if p.text.strip()]  # type: ignore[attr-defined]
    return "\n".join(parts)[:limit]


def read_pptx(raw: bytes, limit: int) -> str:
    """The text of every slide, each under its number."""
    from pptx import Presentation

    deck = _opened(raw, "presentation", Presentation)
    parts: list[str] = []
    for number, slide in enumerate(deck.slides, start=1):  # type: ignore[attr-defined]
        said = [
            shape.text
            for shape in slide.shapes
            if getattr(shape, "has_text_frame", False) and shape.text.strip()
        ]
        if said:
            parts.append(f"Slide {number}\n" + "\n".join(said))
        if len(parts) >= MAX_PARTS or sum(len(p) for p in parts) >= limit:
            break
    return "\n\n".join(parts)[:limit]


def read_xlsx(raw: bytes, limit: int) -> str:
    """Every sheet as rows of tab separated cells."""
    from openpyxl import load_workbook

    book = _opened(raw, "spreadsheet", lambda stream: load_workbook(stream, read_only=True))
    parts: list[str] = []
    size = 0
    for sheet in book.worksheets:  # type: ignore[attr-defined]
        parts.append(f"Sheet {sheet.title}")
        for row in sheet.iter_rows(values_only=True):
            line = "\t".join("" if cell is None else str(cell) for cell in row)
            if not line.strip():
                continue
            parts.append(line)
            size += len(line)
            if len(parts) >= MAX_PARTS or size >= limit:
                break
        if len(parts) >= MAX_PARTS or size >= limit:
            break
    return "\n".join(parts)[:limit]
