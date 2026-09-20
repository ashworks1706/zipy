"""Showing one example to a reviewer and reading back the verdict.

The loop is a terminal one because the judgment is the slow part. An example is shown as the
question that was asked, the tools the reply called for, and the reply itself.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from testbed.core.types import Answer, TrainingExample

#: What each key means.
ANSWERS: dict[str, Answer] = {
    "k": "keep",
    "d": "drop",
    "f": "fix",
    "s": "skip",
    "q": "quit",
}

# Square brackets would be read as rich markup and the keys would vanish.
PROMPT = "(k)eep  (d)rop  (f)ix  (s)kip  (q)uit"

#: How much of a long message is shown before it is cut.
WIDTH = 2000

#: The editor a fix opens when VISUAL and EDITOR are unset.
FALLBACK_EDITOR = "vi"


def _clip(text: str) -> str:
    """One message, cut to WIDTH."""
    return text if len(text) <= WIDTH else f"{text[:WIDTH]}\n... {len(text) - WIDTH} more chars"


def _content(message: dict[str, Any]) -> str:
    """The text of one wire message, whether it is a string or a content array."""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(part.get("text", "") for part in content if isinstance(part, dict))
    return ""


def question(example: TrainingExample) -> str:
    """The last user turn before the reply. Empty when there is none."""
    asked = [_content(m) for m in example.messages if m.get("role") == "user"]
    return asked[-1] if asked else ""


def calls(example: TrainingExample) -> str:
    """The tool calls the reply asked for, one per line."""
    lines = []
    for call in example.tool_calls:
        function = call.get("function") or {}
        lines.append(f"{function.get('name', '?')}({function.get('arguments', '')})")
    return "\n".join(lines)


def show(console: Console, example: TrainingExample, index: int, total: int) -> None:
    """Print one example: what was asked, what it called for, and what it replied."""
    facts = Table.grid(padding=(0, 2))
    facts.add_row("id", example.id)
    facts.add_row("model", example.model)
    facts.add_row("platform", example.platform)
    facts.add_row("messages", str(len(example.messages)))
    console.print(Panel(facts, title=f"example {index} of {total}", title_align="left"))
    console.print(Panel(_clip(question(example)), title="asked", title_align="left"))
    asked_for = calls(example)
    if asked_for:
        console.print(Panel(asked_for, title="called", title_align="left"))
    console.print(Panel(_clip(example.reply), title="replied", title_align="left"))


def edit(text: str) -> str | None:
    """The text after the reviewer edited it. None when nothing changed or the editor failed."""
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or FALLBACK_EDITOR
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "reply.md"
        path.write_text(text, encoding="utf-8")
        try:
            completed = subprocess.run([*shlex.split(editor), str(path)], check=False)
        except OSError:
            return None
        if completed.returncode != 0:
            return None
        edited = path.read_text(encoding="utf-8")
    return None if edited.strip() == text.strip() else edited.strip()


def answer(console: Console, reply: str) -> Answer:
    """One answer to the prompt as the word it means. An unknown key asks again."""
    while True:
        key = reply.strip().lower()[:1]
        if key in ANSWERS:
            return ANSWERS[key]
        console.print(f"[yellow]{PROMPT}[/yellow]")
        reply = console.input("> ")


def as_json(example: TrainingExample) -> str:
    """One example as the JSON a reviewer reads when they want all of it."""
    return json.dumps(example.model_dump(mode="json"), indent=2)
