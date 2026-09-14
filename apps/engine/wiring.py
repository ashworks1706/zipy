"""The composition root: builds every dependency from config and runs the process.

Platforms, the HTTP server and the scheduler share one event loop. Trace events fan out to the
JSONL files under telemetry.trace_dir, LangFuse, and the local platform when it runs.
"""

from __future__ import annotations

from collections.abc import Sequence

from engine.core.config import Config


async def serve(config: Config, only: Sequence[str] = ()) -> None:
    """Build stores, models, registries, agent, gateway, platforms, API and workers; run them.

    only runs just the named platforms, enabled or not, and skips the HTTP server when none of
    them needs it: zipy chat is serve with only local.
    """
    raise NotImplementedError
