"""The TraceSink over LangFuse: one trace per request, one span per model and tool call."""

from __future__ import annotations

from typing import Any

from engine.core.config import Telemetry
from engine.core.types import RequestContext


class LangfuseTrace:
    """Sends trace events to LangFuse. With no keys configured it records nothing."""

    def __init__(self, telemetry: Telemetry) -> None:
        self._telemetry = telemetry

    def event(self, ctx: RequestContext, name: str, data: dict[str, Any]) -> None:
        """Record one event under the request's trace."""
        raise NotImplementedError
