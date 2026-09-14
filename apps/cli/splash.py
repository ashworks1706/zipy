"""The splash screen: the logo animation, then the console. Any key skips it."""

from __future__ import annotations

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Center, Middle
from textual.screen import Screen
from textual.widgets import Static

from cli.logo import COLOR, animation

# How long the settled logo holds before the console appears, in seconds.
HOLD = 0.6


class Splash(Screen[None]):
    """Plays the logo once and dismisses itself."""

    CSS = """
    Splash { background: #000000; }
    #logo { width: auto; height: auto; }
    #tagline { width: auto; margin-top: 1; color: #8e8397; }
    """

    def __init__(self) -> None:
        super().__init__()
        self.frames, self.logo = animation()
        self.index = 0

    def compose(self) -> ComposeResult:
        with Middle(), Center():
            yield Static(id="logo")
        with Center():
            yield Static("collaborative agents for team logistics", id="tagline")

    def on_mount(self) -> None:
        self._show()

    def _show(self) -> None:
        logo = self.query_one("#logo", Static)
        if self.index < len(self.frames):
            frame = self.frames[self.index]
            logo.update(Text(frame.text, style=COLOR))
            self.index += 1
            self.set_timer(frame.seconds or 0.1, self._show)
        else:
            logo.update(Text(self.logo, style=f"bold {COLOR}"))
            self.set_timer(HOLD, self._done)

    def _done(self) -> None:
        if self.is_current:
            self.dismiss()

    def on_key(self, event: events.Key) -> None:
        event.stop()
        self._done()
