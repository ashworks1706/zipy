"""An asyncio loop per periodic job, and one consuming the job queue."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True)
class Periodic:
    """A job run every interval."""

    name: str
    interval: timedelta
    run: Callable[[], Awaitable[None]]


class Scheduler:
    """Runs periodic jobs until stopped. A failing run is logged and does not stop the loop."""

    def __init__(self, jobs: list[Periodic]) -> None:
        self._jobs = jobs

    async def run(self) -> None:
        """Run every job on its interval until cancelled."""
        raise NotImplementedError
