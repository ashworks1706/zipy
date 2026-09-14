"""Redis: the per-user rate limiter and the background job queue."""

from __future__ import annotations

from engine.core.config import Data, RateLimit
from engine.core.types import Job, MemberRef, OrgId


class RedisRateLimiter:
    """A fixed one-minute window per org and member."""

    def __init__(self, data: Data, limits: RateLimit) -> None:
        raise NotImplementedError

    async def allow(self, org_id: OrgId, member: MemberRef) -> bool:
        """True when the member is under the limit, counting this message."""
        raise NotImplementedError


class RedisQueue:
    """A list-backed job queue."""

    def __init__(self, data: Data) -> None:
        raise NotImplementedError

    async def enqueue(self, job: Job) -> None:
        """Push a job."""
        raise NotImplementedError

    async def next(self) -> Job | None:
        """Pop the oldest job, or None when the queue is empty."""
        raise NotImplementedError
