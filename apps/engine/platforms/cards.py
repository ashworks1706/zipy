"""The one message a turn lives in: steps while it runs, then the answer.

The engine writes the text of every step; this only decides what the message looks like as they
arrive. A line carrying a slot writes over the earlier line in that slot, so a tool result
replaces the line that said the tool had started.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.core.types import Progress

#: Header while the turn runs, after the spinner frame.
THINKING = "**Zipy is working on it...**"

#: Header once the answer is being written.
ANSWERING = "**Zipy is answering...**"

#: Frames the header spinner cycles through, one per edit of a running card.
SPINNER = ("◐", "◓", "◑", "◒")

#: Prefix of one step line. The emoji the engine sends is the only marker a step carries.
BULLET = "-# "

#: What one level of delegation indents a step by.
INDENT = "\u2514 "


@dataclass
class _Step:
    """One step line, the key of the line it replaces, and how deep it happened."""

    slot: str | None
    text: str
    depth: int = 0

    def shown(self) -> str:
        """The line as it reads, indented once per level of delegation."""
        return f"{INDENT * self.depth}{self.text}"


@dataclass
class Card:
    """The steps reported for one turn, in order, and the answer written so far."""

    lines: list[_Step] = field(default_factory=list)
    draft: str | None = None
    #: Raised by apply when what the card shows has changed since the last edit.
    dirty: bool = False
    _frame: int = 0

    def apply(self, update: Progress) -> None:
        """Take one progress line. Sets dirty when the card now shows something different."""
        if self._apply(update):
            self.dirty = True

    def _apply(self, update: Progress) -> bool:
        if update.draft:
            if update.clear:
                had = self.draft is not None
                self.draft = None
                return had
            text = update.text.strip()
            if not text or self.draft == text:
                return False
            self.draft = text
            return True
        if update.clear and update.slot is not None:
            return self._clear(update.slot)
        return self._push(update.slot, update.text, update.depth)

    def _push(self, slot: str | None, text: str, depth: int = 0) -> bool:
        """Record a step. A slot writes over the line already in that slot."""
        text = text.strip()
        if not text:
            return False
        if slot is not None:
            for line in self.lines:
                if line.slot == slot:
                    if line.text == text:
                        return False
                    line.text = text
                    return True
        if self.lines and self.lines[-1].text == text:
            return False
        self.lines.append(_Step(slot=slot, text=text, depth=depth))
        return True

    def _clear(self, slot: str) -> bool:
        """Remove the line of a slot. False when there was none."""
        kept = [line for line in self.lines if line.slot != slot]
        if len(kept) == len(self.lines):
            return False
        self.lines = kept
        return True

    def running(self) -> str:
        """The message while the turn runs. Each call advances the spinner."""
        self._frame = (self._frame + 1) % len(SPINNER)
        header = ANSWERING if self.draft else THINKING
        return self._body(f"{SPINNER[self._frame]} {header}")

    def finished(self, answer: str) -> str:
        """The message once the turn is done, with the steps kept above the answer."""
        text = answer.strip()
        body = "\n".join(f"{BULLET}{line.shown()}" for line in self.lines)
        if body and text:
            return f"{body}\n\n{text}"
        return text or body or "I have nothing to say about that."

    def _body(self, header: str) -> str:
        parts = [header]
        parts.extend(f"{BULLET}{line.shown()}" for line in self.lines)
        if self.draft:
            parts.append("")
            parts.append(self.draft)
        return "\n".join(parts)
