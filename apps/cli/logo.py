"""The Zipy logo animation, read from the ASCII Motion exports in assets/.

logo-animated.json is played once, and logo.json is the frame it settles on. The website's copy in
apps/website/lib/cli-frames.ts is generated from the same files by scripts/sync-ascii-frames.py.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files

# The logo's color in the exports.
COLOR = "#ff009f"


@dataclass(frozen=True)
class Frame:
    """One frame of text and how long it shows, in seconds."""

    text: str
    seconds: float


def _frames(name: str) -> list[Frame]:
    data = json.loads(files("cli").joinpath("assets", name).read_text(encoding="utf-8"))
    return [
        Frame(str(f.get("contentString", "")), float(f.get("duration", 0)) / 1000)
        for f in data["frames"]
    ]


def trim(texts: list[str]) -> list[str]:
    """Each text with the rows and columns blank in every text removed, so all keep one size."""
    grid = [t.split("\n") for t in texts]
    height = max(len(rows) for rows in grid)
    grid = [rows + [""] * (height - len(rows)) for rows in grid]
    used_rows = [i for i in range(height) if any(rows[i].strip() for rows in grid)]
    if not used_rows:
        return ["" for _ in texts]
    width = max(len(line) for rows in grid for line in rows)
    used_cols = [
        c for c in range(width) if any(c < len(line) and line[c] != " " for r in grid for line in r)
    ]
    top, bottom, left, right = used_rows[0], used_rows[-1], used_cols[0], used_cols[-1]
    return [
        "\n".join(
            line.ljust(right + 1)[left : right + 1].rstrip() for line in rows[top : bottom + 1]
        )
        for rows in grid
    ]


def animation() -> tuple[list[Frame], str]:
    """The frames to play, trimmed to the logo's size, and the logo they settle on."""
    played = _frames("logo-animated.json")
    logo = _frames("logo.json")[0]
    texts = trim([f.text for f in played] + [logo.text])
    return [Frame(t, f.seconds) for t, f in zip(texts, played, strict=False)], texts[-1]
