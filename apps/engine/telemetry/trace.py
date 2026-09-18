"""Trace sinks that need no service: one JSONL file per request, and a fan-out to several sinks.

A trace sink never stops a request. A file that cannot be written drops the event.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from engine.core.protocols import TraceSink
from engine.core.types import RequestContext


def record(ctx: RequestContext, name: str, data: dict[str, Any], at: datetime) -> dict[str, Any]:
    """One trace event as the JSON object every sink writes."""
    record: dict[str, Any] = {
        "at": at.isoformat(),
        "request_id": ctx.request_id,
        "org_id": ctx.org_id,
        "platform": ctx.channel.platform,
        "workspace_id": ctx.channel.workspace.workspace_id,
        "channel_id": ctx.channel.channel_id,
        "thread_id": ctx.channel.thread_id,
        "member": ctx.member.user_id,
        "event": name,
        "data": data,
    }
    if ctx.depth or ctx.parent:
        record["depth"] = ctx.depth
        record["parent"] = ctx.parent
    return record


class JsonlTrace:
    """Appends each event to directory/<org_id>/<request_id>.jsonl. Satisfies TraceSink."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def path(self, ctx: RequestContext) -> Path:
        """The file one request's events go to."""
        return self.directory / ctx.org_id / f"{ctx.request_id}.jsonl"

    def event(self, ctx: RequestContext, name: str, data: dict[str, Any]) -> None:
        target = self.path(ctx)
        line = json.dumps(record(ctx, name, data, datetime.now(UTC)), default=str)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError:
            return


class Fanout:
    """Sends each event to every sink in order. Satisfies TraceSink."""

    def __init__(self, sinks: Sequence[TraceSink]) -> None:
        self.sinks = tuple(sinks)

    def event(self, ctx: RequestContext, name: str, data: dict[str, Any]) -> None:
        for sink in self.sinks:
            sink.event(ctx, name, data)
