#!/usr/bin/env -S uv run python
"""Copy the console's logo animation into the website.

Writes apps/website/lib/cli-frames.ts from the ASCII Motion exports in apps/cli/assets, trimmed
by cli.logo exactly as the console plays them. Run with just web-frames.
"""

import json
import pathlib
import sys

from cli.logo import animation

root = pathlib.Path(__file__).resolve().parent.parent
dst = root / "apps/website/lib/cli-frames.ts"

frames, logo = animation()
rows = logo.split("\n")
dst.parent.mkdir(parents=True, exist_ok=True)
dst.write_text(
    "// Generated from apps/cli/assets/logo-animated.json and logo.json, as the console plays.\n"
    "// Regenerate with just web-frames after changing either file.\n\n"
    "export type CliFrame = { text: string; ms: number };\n\n"
    "export const CLI_FRAMES: CliFrame[] = "
    + json.dumps(
        [{"text": f.text, "ms": round(f.seconds * 1000)} for f in frames],
        ensure_ascii=False,
        indent=2,
    )
    + ";\n\n"
    + f"export const CLI_LOGO: string = {json.dumps(logo, ensure_ascii=False)};\n\n"
    + f"export const CLI_COLUMNS = {max(len(r) for r in rows)};\n"
    + f"export const CLI_ROWS = {len(rows)};\n",
    encoding="utf-8",
)
sys.stdout.write(f"wrote {len(frames)} frames and the logo to {dst.relative_to(root)}\n")
