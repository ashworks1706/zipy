"""The background workers: the scheduler, cleanup, token refresh, ingestion and the spend reset."""

import asyncio
import math
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel, SecretStr

from engine.auth.providers.base import BaseProvider
from engine.auth.providers.registry import Providers
from engine.core.config import Memory, ProviderSettings, ToolSettings, Workers
from engine.core.doubles import (
    FixedEmbedder,
    MemoryConfirmations,
    MemoryCredentials,
    MemoryDocuments,
    MemoryNotifier,
    MemoryOrgs,
    MemoryQueue,
    NoLimit,
)
from engine.core.types import (
    ActionType,
    CredentialError,
    Document,
    IngestError,
    Job,
    OAuthError,
    Org,
    OrgId,
    PendingConfirmation,
    ProviderAuth,
    ToolCall,
)
from engine.telemetry.metrics import Metrics
from engine.tools.base import Action, BaseTool
from engine.tools.registry import Registry
from engine.workers.cleanup import cleanup
from engine.workers.ingestion import Ingestion, document_job, sync_job
from engine.workers.scheduler import Consumer, DailyAt, MonthlyFirst, Periodic, Scheduler
from engine.workers.spend import reset_monthly_spend
from engine.workers.token_refresh import refresh_expiring

ORG = OrgId("org-1")
NOW = datetime(2026, 9, 15, 5, 0, tzinfo=UTC)


# ---------------------------------------------------------------- doubles


@dataclass
class PruningDocuments(MemoryDocuments):
    """A document store that records what it was asked to prune."""

    pruned: list[tuple[str, datetime]] = field(default_factory=list)

    async def prune(self, source: str, older_than: datetime) -> int:
        self.pruned.append((source, older_than))
        return 1


class Settings(BaseModel):
    """The fake tool's only setting."""

    limit: int = 10


class Params(BaseModel):
    """Arguments of the read action."""

    day: str


class Result(BaseModel):
    """Result of the read action."""

    events: list[str]


class Diary(BaseTool[Settings]):
    """A syncing tool over a provider."""

    name: ClassVar[str] = "diary"
    provider: ClassVar[str] = "google"
    syncs: ClassVar[bool] = True
    settings_model: ClassVar[type[BaseModel]] = Settings
    actions: ClassVar[Mapping[str, Action]] = {
        "list_events": Action("List the events of a day.", Params, Result)
    }

    async def execute(self, action, params, auth):
        return Result(events=[])

    async def documents(
        self, auth: ProviderAuth | None, since: datetime | None, source_id: str = ""
    ) -> AsyncIterator[Document]:
        if auth is None or auth.provider != "google":
            raise CredentialError("no credential reached the tool")
        names = [source_id] if source_id else ["d1", "d2"]
        for name in names:
            yield Document(
                source="diary",
                source_id=name,
                title=f"Minutes {name}",
                text=f"{name} we agreed to buy motors",
                updated_at=since or NOW,
            )


class Quiet(Diary):
    """A tool that does not sync."""

    name: ClassVar[str] = "quiet"
    syncs: ClassVar[bool] = False


class Grant(BaseModel):
    """The fake provider's settings."""

    client_id: str = "id"


class Google(BaseProvider[Grant]):
    """A provider whose refresh can be told to fail."""

    name: ClassVar[str] = "google"
    settings_model: ClassVar[type[BaseModel]] = Grant
    revoked: ClassVar[bool] = False

    def authorize_url(self, state: str, scopes: list[str]) -> str:
        return f"https://google.test/auth?state={state}"

    async def exchange(self, org_id: OrgId, code: str) -> ProviderAuth:
        raise OAuthError("not used")

    async def refresh(self, auth: ProviderAuth) -> ProviderAuth:
        if Google.revoked:
            raise OAuthError("the grant was revoked")
        return replace(
            auth, access_token=SecretStr("fresh-token"), expires_at=NOW + timedelta(days=1)
        )


def providers(revoked: bool = False) -> Providers:
    """A registry holding the fake provider."""
    Google.revoked = revoked
    return Providers({"google": ProviderSettings()}, "http://zipy.test", {"google": Google})


def registry() -> Registry:
    """A registry over the fake tools."""
    actions = {"list_events": ActionType.READ}
    return Registry(
        {
            "diary": ToolSettings(provider="google", actions=actions),
            "quiet": ToolSettings(provider="google", actions=actions),
        },
        {"diary": Diary, "quiet": Quiet},
    )


def credential(expires_at: datetime | None) -> MemoryCredentials:
    """A credential store holding one google credential for the org."""
    store = MemoryCredentials()
    store.auths[(ORG, "google")] = ProviderAuth(
        org_id=ORG,
        provider="google",
        access_token=SecretStr("stale-token"),
        scopes=("calendar",),
        expires_at=expires_at,
        refresh_token=SecretStr("refresh"),
    )
    return store


def ingestion(
    credentials: MemoryCredentials, store: MemoryDocuments, limiter: Any = None
) -> Ingestion:
    """An ingestion worker over the fake tools."""
    return Ingestion(
        registry=registry(),
        memory=Memory(chunk_tokens=5, chunk_overlap_tokens=1),
        credentials=credentials,
        embedder=FixedEmbedder([0.1]),
        documents=store,
        limiter=limiter if limiter is not None else NoLimit(),
    )


# ---------------------------------------------------------------- the scheduler


async def test_a_periodic_job_runs_again_on_every_interval():
    runs = 0

    async def job() -> None:
        nonlocal runs
        runs += 1

    scheduler = Scheduler([Periodic("tick", timedelta(seconds=0.01), job)])
    task = asyncio.create_task(scheduler.run())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert runs >= 2


async def test_a_failing_job_is_logged_and_the_loop_carries_on():
    runs = 0

    async def job() -> None:
        nonlocal runs
        runs += 1
        raise IngestError("the source is down")

    scheduler = Scheduler([Periodic("tick", timedelta(seconds=0.01), job)])
    await scheduler.tick()
    await scheduler.tick()
    assert runs == 2, "a raising job is run again rather than ending its loop"


async def test_a_daily_job_runs_once_a_day_at_its_hour():
    runs: list[datetime] = []
    clock = {"now": datetime(2026, 9, 15, 3, 0, tzinfo=UTC)}

    async def job() -> None:
        runs.append(clock["now"])

    daily = DailyAt(hour_utc=4, job=job, clock=lambda: clock["now"])
    await daily.tick()
    assert runs == [], "nothing runs before the hour"
    clock["now"] = datetime(2026, 9, 15, 4, 30, tzinfo=UTC)
    await daily.tick()
    await daily.tick()
    assert len(runs) == 1, "the hour comes round once a day"
    clock["now"] = datetime(2026, 9, 16, 4, 0, tzinfo=UTC)
    await daily.tick()
    assert len(runs) == 2


async def test_a_monthly_job_runs_once_on_the_first():
    runs = 0

    async def job() -> None:
        nonlocal runs
        runs += 1

    clock = {"now": datetime(2026, 9, 15, tzinfo=UTC)}
    monthly = MonthlyFirst(job=job, clock=lambda: clock["now"])
    await monthly.tick()
    assert runs == 0
    clock["now"] = datetime(2026, 10, 1, 2, 0, tzinfo=UTC)
    await monthly.tick()
    await monthly.tick()
    assert runs == 1
    clock["now"] = datetime(2026, 11, 1, tzinfo=UTC)
    await monthly.tick()
    assert runs == 2


async def test_the_consumer_drains_the_queue_and_counts_every_job():
    queue = MemoryQueue()
    metrics = Metrics()
    handled: list[str] = []

    async def handler(job: Job) -> None:
        handled.append(job.kind)
        if job.kind == "boom":
            raise IngestError("that job failed")

    await queue.enqueue(Job(kind=sync_job("diary"), org_id=ORG))
    await queue.enqueue(Job(kind="boom", org_id=ORG))
    ran = await Consumer(queue, handler, metrics=metrics).drain()
    assert ran == 2
    assert handled == ["sync:diary", "boom"], "a failing job never stops the queue"
    snapshot = metrics.snapshot()
    assert snapshot["zipy_jobs_total{kind=sync:diary,outcome=ok}"] == 1
    assert snapshot["zipy_jobs_total{kind=boom,outcome=error}"] == 1
    assert not any(str(ORG) in key for key in snapshot), "jobs are never labelled by org"


# ---------------------------------------------------------------- cleanup


async def test_cleanup_drops_expired_confirmations_and_prunes_by_retention():
    confirmations = MemoryConfirmations()
    for name, expiry in (("old", NOW - timedelta(hours=1)), ("live", NOW + timedelta(days=400))):
        confirmations.pending[name] = PendingConfirmation(
            id=name,
            org_id=ORG,
            requested_by=None,  # type: ignore[arg-type]
            channel=None,  # type: ignore[arg-type]
            call=ToolCall(id="c1", name="diary.move_event", arguments={}),
            summary="move",
            expires_at=expiry,
        )
    documents = PruningDocuments()
    memory = Memory(retention_days={"zoom": 180, "notion": 365})
    await cleanup(memory, confirmations, documents)
    assert set(confirmations.pending) == {"live"}
    assert [source for source, _ in documents.pruned] == ["zoom", "notion"]
    cutoffs = dict(documents.pruned)
    assert (cutoffs["zoom"] - cutoffs["notion"]).days == 185


async def test_cleanup_prunes_nothing_when_no_source_has_a_retention():
    documents = PruningDocuments()
    await cleanup(Memory(retention_days={}), MemoryConfirmations(), documents)
    assert documents.pruned == []


# ---------------------------------------------------------------- token refresh


async def test_a_credential_inside_the_window_is_refreshed():
    workers = Workers()
    credentials = credential(datetime.now(UTC) + timedelta(minutes=30))
    notifier = MemoryNotifier()
    await refresh_expiring(workers, credentials, providers(), notifier)
    stored = credentials.auths[(ORG, "google")]
    assert stored.access_token.get_secret_value() == "fresh-token"
    assert notifier.sent == [], "a working refresh says nothing to the org"


async def test_a_credential_outside_the_window_is_left_alone():
    credentials = credential(datetime.now(UTC) + timedelta(days=2))
    await refresh_expiring(Workers(), credentials, providers(), MemoryNotifier())
    assert credentials.auths[(ORG, "google")].access_token.get_secret_value() == "stale-token"


async def test_a_revoked_grant_is_marked_invalid_and_the_org_is_told():
    credentials = credential(datetime.now(UTC) + timedelta(minutes=30))
    notifier = MemoryNotifier()
    await refresh_expiring(Workers(), credentials, providers(revoked=True), notifier)
    assert await credentials.get(ORG, "google") is None
    assert await credentials.connected(ORG) == frozenset()
    assert notifier.sent[0][0] == ORG
    assert "google" in notifier.sent[0][1] and "connect google" in notifier.sent[0][1]


async def test_a_credential_whose_provider_is_disabled_is_skipped():
    credentials = credential(datetime.now(UTC) + timedelta(minutes=30))
    disabled = Providers(
        {"google": ProviderSettings(enabled=False)}, "http://x", {"google": Google}
    )
    await refresh_expiring(Workers(), credentials, disabled, MemoryNotifier())
    assert credentials.auths[(ORG, "google")].access_token.get_secret_value() == "stale-token"


# ---------------------------------------------------------------- ingestion


async def test_a_sync_job_ingests_every_document_of_the_tool():
    store = MemoryDocuments()
    await ingestion(credential(None), store).run(Job(kind=sync_job("diary"), org_id=ORG))
    assert {chunk.source_id for chunk in store.chunks} == {"d1", "d2"}
    assert {chunk.org_id for chunk in store.chunks} == {ORG}
    assert {chunk.source for chunk in store.chunks} == {"diary"}


async def test_a_sync_spends_one_of_the_provider_budget_for_each_document():
    limiter = NoLimit()
    await ingestion(credential(None), MemoryDocuments(), limiter).run(
        Job(kind=sync_job("diary"), org_id=ORG)
    )
    # Two documents, so the sync paces itself twice rather than fetching the page at once.
    assert limiter.taken == [(ORG, "google"), (ORG, "google")]


async def test_a_sync_waits_as_long_as_it_needs_to():
    budgets: list[float] = []

    class Recording:
        async def acquire(self, org_id: OrgId, provider: str, max_wait: float) -> None:  # noqa: ARG002 - protocol signature
            budgets.append(max_wait)

    await ingestion(credential(None), MemoryDocuments(), Recording()).run(
        Job(kind=sync_job("diary"), org_id=ORG)
    )
    # Nobody is waiting on a reply, so a sync never gives up on the budget.
    assert budgets and all(budget == math.inf for budget in budgets)


async def test_a_document_job_ingests_only_the_document_it_names():
    store = MemoryDocuments()
    await ingestion(credential(None), store).run(
        Job(kind=document_job("diary"), org_id=ORG, payload={"source_id": "d7"})
    )
    assert {chunk.source_id for chunk in store.chunks} == {"d7"}


async def test_a_document_job_without_a_source_id_says_so():
    with pytest.raises(IngestError, match="source_id"):
        await ingestion(credential(None), MemoryDocuments()).run(
            Job(kind=document_job("diary"), org_id=ORG)
        )


async def test_a_sync_job_passes_the_since_of_its_payload():
    store = MemoryDocuments()
    since = datetime(2026, 8, 1, tzinfo=UTC)
    await ingestion(credential(None), store).run(
        Job(kind=sync_job("diary"), org_id=ORG, payload={"since": since.isoformat()})
    )
    assert store.chunks[0].metadata["updated_at"] == since.isoformat()


async def test_an_unknown_job_kind_is_an_error():
    with pytest.raises(IngestError, match="unknown job kind"):
        await ingestion(credential(None), MemoryDocuments()).run(Job(kind="polish", org_id=ORG))


async def test_a_tool_that_does_not_sync_is_an_error():
    with pytest.raises(IngestError, match="quiet"):
        await ingestion(credential(None), MemoryDocuments()).run(
            Job(kind=sync_job("quiet"), org_id=ORG)
        )


async def test_an_org_without_the_credential_is_an_error_naming_the_provider():
    with pytest.raises(CredentialError, match="google"):
        await ingestion(MemoryCredentials(), MemoryDocuments()).run(
            Job(kind=sync_job("diary"), org_id=ORG)
        )


async def test_the_consumer_runs_ingestion_jobs_off_the_queue():
    store = MemoryDocuments()
    queue = MemoryQueue()
    await queue.enqueue(Job(kind=sync_job("diary"), org_id=ORG))
    assert await Consumer(queue, ingestion(credential(None), store).run).drain() == 1
    assert {chunk.source_id for chunk in store.chunks} == {"d1", "d2"}


# ---------------------------------------------------------------- spend


async def test_the_monthly_reset_zeroes_every_org():
    orgs = MemoryOrgs()
    orgs.orgs[ORG] = Org(ORG, "Robotics Club", True, 200, 175)
    other = OrgId("org-2")
    orgs.orgs[other] = Org(other, "Chess Club", True, 200, 20)
    await reset_monthly_spend(orgs)
    assert [org.spent_cents for org in orgs.orgs.values()] == [0, 0]
    assert orgs.orgs[ORG].budget_cents == 200, "the budget is untouched"
