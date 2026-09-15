"""The trace sink that turns events into live progress lines for a watcher."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from engine.core.types import Progress, ProgressStyle, RequestContext, progress

#: What a watcher is handed for each line.
Watcher = Callable[[Progress], None]


class ProgressSink:
    """Renders each event as a line for the request's watcher. Bookkeeping events write none.

    Without a watcher of its own it reads ctx.watcher, so one sink built at startup serves every
    request and the model client and the tool executor need no wiring of their own.
    """

    def __init__(self, watcher: Watcher | None = None, style: ProgressStyle | None = None) -> None:
        self._watcher = watcher
        self._style = style or ProgressStyle()

    def event(self, ctx: RequestContext, name: str, data: dict[str, Any]) -> None:
        """Write the line for one event, when it has one and this request is being watched."""
        watcher = self._watcher or ctx.watcher
        if watcher is None:
            return
        line = progress(name, data, self._style)
        if line is not None:
            watcher(line)
