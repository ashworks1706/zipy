"""Read one file into text, inside the sandbox.

The engine writes the bytes into the workspace and runs this. It prints a JSON object on one
line: {"text": "..."} for a file it read, {"error": "..."} for one it could not. Nothing is
printed to stderr that the caller relies on, and nothing here reaches the network.

The parsers are the engine's own, copied into the image. They import nothing from engine, so the
file the model reads is produced by the same code whether parsing runs here or in the process.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from parsers.errors import ParseError
from parsers.registry import parser_for


def main(argv: list[str]) -> int:
    """Read the file named by argv and print what it says."""
    if len(argv) != 4:
        print(json.dumps({"error": "usage: extract.py PATH MEDIA_TYPE MAX_CHARS"}))
        return 2
    path, media_type, limit = argv[1], argv[2], argv[3]
    parser = parser_for(media_type)
    if parser is None:
        print(json.dumps({"error": f"nothing here reads {media_type}"}))
        return 1
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        print(json.dumps({"error": f"could not read {path}: {type(exc).__name__}"}))
        return 1
    try:
        text = parser(raw, int(limit))
    except ParseError as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    except (ValueError, MemoryError, RecursionError) as exc:
        print(json.dumps({"error": f"that file could not be read: {type(exc).__name__}"}))
        return 1
    print(json.dumps({"text": text}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
