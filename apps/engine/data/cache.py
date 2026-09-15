"""Redis: the per-user rate limiter and the background job queue."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from engine.core.config import Data, RateLimit
from engine.core.types import ConfigError, Job, MemberRef, OrgId, StoreError

QUEUE_KEY = "zipy:jobs"

WINDOW_SECONDS = 60


def rate_key(org_id: OrgId, member: MemberRef, at: datetime) -> str:
    """The counter key for one member of one org in the window containing at."""
    window = int(at.timestamp()) // WINDOW_SECONDS
    return f"zipy:rate:{org_id}:{member.platform}:{member.user_id}:{window}"


def encode_job(job: Job) -> str:
    """A job as the JSON a queue entry holds."""
    return json.dumps(
        {"kind": job.kind, "org_id": str(job.org_id), "payload": job.payload}, sort_keys=True
    )


def decode_job(entry: str | bytes) -> Job:
    """The job a queue entry holds. An entry of any other shape is a StoreError."""
    try:
        fields: Any = json.loads(entry)
    except ValueError as exc:
        raise StoreError("a queued job is not JSON") from exc
    if not isinstance(fields, dict):
        raise StoreError("a queued job is not a JSON object")
    kind = fields.get("kind")
    org_id = fields.get("org_id")
    payload = fields.get("payload", {})
    if not isinstance(kind, str) or not kind:
        raise StoreError("a queued job has no kind")
    if not isinstance(org_id, str) or not org_id:
        raise StoreError(f"the queued job {kind} has no org_id")
    if not isinstance(payload, dict):
        raise StoreError(f"the queued job {kind} has a payload that is not an object")
    return Job(kind=kind, org_id=OrgId(org_id), payload=payload)


def _client(data: Data) -> Redis:
    """A Redis client for ZIPY_DATA__REDIS_URL. An empty URL is a ConfigError."""
    url = data.redis_url.get_secret_value()
    if not url:
        raise ConfigError("data.redis_url is empty; set ZIPY_DATA__REDIS_URL in .env")
    try:
        return Redis.from_url(url, decode_responses=True)
    except (ValueError, RedisError) as exc:
        raise ConfigError(f"data.redis_url is not a usable Redis URL: {exc}") from exc


class RedisRateLimiter:
    """A fixed one-minute window per org and member."""

    def __init__(self, data: Data, limits: RateLimit) -> None:
        self._redis = _client(data)
        self._limit = limits.per_member_per_minute

    async def allow(self, org_id: OrgId, member: MemberRef) -> bool:
        """True when the member is under the limit, counting this message."""
        key = rate_key(org_id, member, datetime.now(UTC))
        try:
            pipeline = self._redis.pipeline()
            pipeline.incr(key)
            pipeline.expire(key, WINDOW_SECONDS)
            used, _ = await pipeline.execute()
        except RedisError as exc:
            raise StoreError(f"the rate limiter failed: {exc}") from exc
        return int(used) <= self._limit


class RedisQueue:
    """A list-backed job queue."""

    def __init__(self, data: Data) -> None:
        self._redis = _client(data)

    async def enqueue(self, job: Job) -> None:
        """Push a job."""
        try:
            await self._redis.lpush(QUEUE_KEY, encode_job(job))
        except RedisError as exc:
            raise StoreError(f"enqueueing {job.kind} failed: {exc}") from exc

    async def next(self) -> Job | None:
        """Pop the oldest job, or None when the queue is empty."""
        try:
            entry = await self._redis.rpop(QUEUE_KEY)
        except RedisError as exc:
            raise StoreError(f"reading the job queue failed: {exc}") from exc
        if entry is None:
            return None
        if not isinstance(entry, str | bytes):
            raise StoreError("the job queue holds an entry that is not a job")
        return decode_job(entry)
