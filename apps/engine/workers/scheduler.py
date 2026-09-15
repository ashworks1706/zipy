"""An asyncio loop per periodic job, and one consuming the job queue."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from engine.core.protocols import JobQueue
from engine.core.types import Job
from engine.telemetry.logging import get
from engine.telemetry.metrics import Metrics

log = get("engine.workers")


def now_utc() -> datetime:
    """The current time in UTC."""
    return datetime.now(UTC)


@dataclass(frozen=True)
class Periodic:
    """A job run every interval."""

    name: str
    interval: timedelta
    run: Callable[[], Awaitable[None]]


@dataclass
class DailyAt:
    """Runs its job once a day, on the first tick at or after hour_utc."""

    hour_utc: int
    job: Callable[[], Awaitable[None]]
    clock: Callable[[], datetime] = now_utc
    last_run: date | None = field(default=None)

    async def tick(self) -> None:
        """Run the job when today's hour has come and today has not run yet."""
        moment = self.clock()
        if moment.hour < self.hour_utc or self.last_run == moment.date():
            return
        self.last_run = moment.date()
        await self.job()


@dataclass
class MonthlyFirst:
    """Runs its job once a month, on the first tick on the first day of the month."""

    job: Callable[[], Awaitable[None]]
    clock: Callable[[], datetime] = now_utc
    last_run: tuple[int, int] | None = field(default=None)

    async def tick(self) -> None:
        """Run the job on the first of the month when this month has not run yet."""
        moment = self.clock()
        month = (moment.year, moment.month)
        if moment.day != 1 or self.last_run == month:
            return
        self.last_run = month
        await self.job()


class Scheduler:
    """Runs periodic jobs until stopped. A failing run is logged and does not stop the loop."""

    def __init__(self, jobs: list[Periodic]) -> None:
        self._jobs = jobs

    async def run(self) -> None:
        """Run every job on its interval until cancelled."""
        async with asyncio.TaskGroup() as group:
            for job in self._jobs:
                group.create_task(self._loop(job), name=f"periodic:{job.name}")

    async def tick(self) -> None:
        """Run every job once, for a single sweep outside the loop."""
        for job in self._jobs:
            await self._once(job)

    async def _loop(self, job: Periodic) -> None:
        """Sleep the interval, run the job, forever."""
        while True:
            await asyncio.sleep(job.interval.total_seconds())
            await self._once(job)

    async def _once(self, job: Periodic) -> None:
        """One run of one job. Anything it raises is logged and dropped."""
        try:
            await job.run()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("periodic job failed", job=job.name)


class Consumer:
    """Takes jobs off the queue and hands each to the handler, until cancelled."""

    def __init__(
        self,
        queue: JobQueue,
        handler: Callable[[Job], Awaitable[None]],
        idle: timedelta = timedelta(seconds=1),
        metrics: Metrics | None = None,
    ) -> None:
        self._queue = queue
        self._handler = handler
        self._idle = idle
        self._metrics = metrics

    async def run(self) -> None:
        """Drain the queue, sleeping idle whenever it is empty."""
        while True:
            if not await self.drain():
                await asyncio.sleep(self._idle.total_seconds())

    async def drain(self) -> int:
        """Run every job waiting on the queue now. Returns how many ran."""
        ran = 0
        while True:
            job = await self._queue.next()
            if job is None:
                return ran
            ran += 1
            await self._handle(job)

    async def _handle(self, job: Job) -> None:
        """One job. A failure is logged and counted, and the queue keeps moving."""
        outcome = "ok"
        try:
            await self._handler(job)
        except asyncio.CancelledError:
            raise
        except Exception:
            outcome = "error"
            log.exception("job failed", kind=job.kind, org_id=str(job.org_id))
        if self._metrics is not None:
            self._metrics.jobs.labels(kind=job.kind, outcome=outcome).inc()
