"""The data layer: the vault, the Redis codecs, and the repositories against Postgres.

Everything that needs a live Postgres or Redis is marked integration; the rest runs with no
services at all.

The integration tests drop and recreate every table of ZIPY_TEST_DATABASE_URL, and skip when it is
unset. They never fall back to ZIPY_DATA__DATABASE_URL: that is the database the developer is
running Zipy against, and a fallback makes running the suite destroy it.
"""

import os
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError

from engine.core.config import Data, ProviderRate, RateLimit
from engine.core.config import load as load_config
from engine.core.types import (
    NEUTRAL,
    AuditEntry,
    ChannelRef,
    Chunk,
    ConfigError,
    Dimension,
    Evidence,
    FactCategory,
    Job,
    MemberRef,
    OrgFact,
    OrgId,
    OrgToolConfig,
    PendingConfirmation,
    ProviderAuth,
    RateLimited,
    Role,
    Signal,
    StoreError,
    ToolCall,
    Workspace,
    WorkspaceRef,
)
from engine.data.cache import (
    QUEUE_KEY,
    RedisProviderLimiter,
    RedisQueue,
    RedisRateLimiter,
    bucket_key,
    decode_job,
    encode_job,
    rate_key,
    refilled,
    wait_for,
)
from engine.data.crypto import Vault
from engine.data.db import create_engine, org_uuid, sessions, store_errors
from engine.data.repos.audit import PgAudit
from engine.data.repos.collaboration import PgCollaboration
from engine.data.repos.confirmations import PgConfirmations
from engine.data.repos.credentials import PgCredentials
from engine.data.repos.documents import PgDocuments
from engine.data.repos.org_context import PgOrgContext
from engine.data.repos.orgs import PgOrgs
from engine.data.repos.tool_config import PgToolConfig
from engine.data.repos.workspaces import PgWorkspaces
from engine.data.tables import EMBEDDING_DIMENSIONS, AuditRow, Base, CredentialRow

DATABASE_URL = os.environ.get("ZIPY_TEST_DATABASE_URL", "")
REDIS_URL = os.environ.get("ZIPY_DATA__REDIS_URL", "redis://127.0.0.1:6379/0")

NO_DATABASE = "set ZIPY_TEST_DATABASE_URL to a throwaway database; these tests drop every table"

BUCKET_ORG = OrgId("bucket-org-1")

MINUTE = datetime(2026, 9, 15, 12, 30, 0, tzinfo=UTC)


def vector(*first):
    """An embedding whose leading components are the ones given and the rest zero."""
    return list(first) + [0.0] * (EMBEDDING_DIMENSIONS - len(first))


# ---------------------------------------------------------------- the vault


def test_a_sealed_token_opens_back_to_the_same_string():
    vault = Vault(SecretStr(Fernet.generate_key().decode()))
    sealed = vault.seal(SecretStr("ya29.a0-secret"))
    assert b"ya29" not in sealed
    assert vault.open(sealed).get_secret_value() == "ya29.a0-secret"


def test_sealing_one_token_twice_gives_two_ciphertexts_that_both_open():
    vault = Vault(SecretStr(Fernet.generate_key().decode()))
    first = vault.seal(SecretStr("token"))
    second = vault.seal(SecretStr("token"))
    assert first != second
    assert vault.open(first).get_secret_value() == "token"
    assert vault.open(second).get_secret_value() == "token"


def test_a_token_sealed_with_another_key_is_a_store_error():
    sealed = Vault(SecretStr(Fernet.generate_key().decode())).seal(SecretStr("token"))
    other = Vault(SecretStr(Fernet.generate_key().decode()))
    with pytest.raises(StoreError):
        other.open(sealed)


def test_a_tampered_ciphertext_is_a_store_error():
    vault = Vault(SecretStr(Fernet.generate_key().decode()))
    sealed = bytearray(vault.seal(SecretStr("token")))
    sealed[-1] ^= 0xFF
    with pytest.raises(StoreError):
        vault.open(bytes(sealed))


@pytest.mark.parametrize("key", ["", "not-a-fernet-key", "c2hvcnQ="])
def test_a_key_that_is_not_a_fernet_key_is_a_config_error(key):
    with pytest.raises(ConfigError):
        Vault(SecretStr(key))


# ---------------------------------------------------------------- the queue codec


def test_a_job_survives_the_queue_encoding():
    job = Job(
        kind="sync:drive", org_id=OrgId(str(uuid4())), payload={"since": "2026-09-01", "n": 3}
    )
    back = decode_job(encode_job(job))
    assert back == job


def test_a_job_with_no_payload_comes_back_with_an_empty_one():
    job = Job(kind="cleanup", org_id=OrgId(str(uuid4())))
    assert decode_job(encode_job(job)).payload == {}


def test_a_job_encodes_to_bytes_a_redis_client_can_return():
    job = Job(kind="cleanup", org_id=OrgId("org-1"))
    assert decode_job(encode_job(job).encode()) == job


@pytest.mark.parametrize(
    "entry",
    [
        "not json at all",
        '["sync:drive"]',
        '{"org_id": "o1", "payload": {}}',
        '{"kind": "", "org_id": "o1"}',
        '{"kind": "sync:drive"}',
        '{"kind": "sync:drive", "org_id": "o1", "payload": []}',
    ],
)
def test_a_queue_entry_that_is_not_a_job_is_a_store_error(entry):
    with pytest.raises(StoreError):
        decode_job(entry)


# ---------------------------------------------------------------- the rate limit window


def test_one_minute_of_messages_shares_a_counter_and_the_next_minute_does_not():
    org, member = OrgId("org-1"), MemberRef("discord", "u1")
    assert rate_key(org, member, MINUTE) == rate_key(org, member, MINUTE + timedelta(seconds=59))
    assert rate_key(org, member, MINUTE) != rate_key(org, member, MINUTE + timedelta(seconds=60))


def test_members_orgs_and_platforms_count_separately():
    org, other = OrgId("org-1"), OrgId("org-2")
    member = MemberRef("discord", "u1")
    keys = {
        rate_key(org, member, MINUTE),
        rate_key(other, member, MINUTE),
        rate_key(org, MemberRef("discord", "u2"), MINUTE),
        rate_key(org, MemberRef("slack", "u1"), MINUTE),
    }
    assert len(keys) == 4


# ---------------------------------------------------------------- the provider token bucket


def test_a_bucket_is_its_own_per_org_and_per_provider():
    org, other = OrgId("org-1"), OrgId("org-2")
    keys = {
        bucket_key(org, "notion"),
        bucket_key(other, "notion"),
        bucket_key(org, "google"),
    }
    assert len(keys) == 3


def test_a_bucket_refills_at_the_configured_rate():
    rate = ProviderRate(per_minute=60, burst=10)
    # 60 a minute is one a second.
    assert refilled(0.0, 1.0, rate) == pytest.approx(1.0)
    assert refilled(0.0, 5.0, rate) == pytest.approx(5.0)


def test_a_bucket_never_holds_more_than_its_burst():
    rate = ProviderRate(per_minute=60, burst=10)
    assert refilled(8.0, 600.0, rate) == pytest.approx(10.0)
    assert refilled(10.0, 0.0, rate) == pytest.approx(10.0)


def test_time_running_backwards_adds_nothing():
    rate = ProviderRate(per_minute=60, burst=10)
    assert refilled(4.0, -30.0, rate) == pytest.approx(4.0)


def test_a_whole_token_waits_for_nothing_and_a_partial_one_waits():
    rate = ProviderRate(per_minute=60, burst=10)
    assert wait_for(1.0, rate) == 0.0
    assert wait_for(3.5, rate) == 0.0
    # A quarter of a token short of one, at one a second.
    assert wait_for(0.75, rate) == pytest.approx(0.25)
    assert wait_for(0.0, rate) == pytest.approx(1.0)


def test_a_slower_provider_waits_longer_for_the_same_shortfall():
    slow = ProviderRate(per_minute=6, burst=2)
    fast = ProviderRate(per_minute=60, burst=2)
    assert wait_for(0.0, slow) > wait_for(0.0, fast)


def test_a_provider_with_no_entry_of_its_own_uses_the_default():
    limits = RateLimit(
        provider=ProviderRate(per_minute=60, burst=10),
        providers={"notion": ProviderRate(per_minute=180, burst=20)},
    )
    assert limits.for_provider("notion").per_minute == 180
    assert limits.for_provider("google").per_minute == 60


@pytest.mark.parametrize(
    "rate",
    [
        {"per_minute": 0},
        {"per_minute": -1},
        {"burst": 0},
    ],
)
def test_a_provider_rate_that_would_never_allow_a_call_is_rejected(rate):
    with pytest.raises(ConfigError):
        ProviderRate(**rate)


def test_a_negative_wait_budget_is_rejected():
    with pytest.raises(ConfigError):
        RateLimit(provider_max_wait_seconds=-1.0)


# ---------------------------------------------------------------- the engine and its helpers


def test_an_empty_database_url_is_a_config_error():
    with pytest.raises(ConfigError):
        create_engine(Data())


def test_a_blocking_driver_url_is_a_config_error():
    with pytest.raises(ConfigError):
        create_engine(Data(database_url=SecretStr("postgresql://zipy@127.0.0.1/zipy")))


def test_an_org_id_that_is_not_a_uuid_is_a_store_error():
    generated = uuid4()
    assert org_uuid(OrgId(str(generated))) == generated
    with pytest.raises(StoreError):
        org_uuid(OrgId("org-1"))


async def test_a_database_failure_is_reported_as_a_store_error():
    with pytest.raises(StoreError, match="orgs.get"):
        async with store_errors("orgs.get"):
            raise OperationalError("select 1", {}, Exception("connection refused"))


async def test_an_error_that_is_not_the_database_travels_unchanged():
    with pytest.raises(ValueError, match="boom"):
        async with store_errors("orgs.get"):
            raise ValueError("boom")


# ---------------------------------------------------------------- Postgres and Redis


@pytest.fixture
async def factory():
    if not DATABASE_URL:
        pytest.skip(NO_DATABASE)
    engine = create_engine(Data(database_url=SecretStr(DATABASE_URL)))
    async with engine.begin() as connection:
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield sessions(engine)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
def vault():
    return Vault(SecretStr(Fernet.generate_key().decode()))


@pytest.fixture
def data():
    if not DATABASE_URL:
        pytest.skip(NO_DATABASE)
    return Data(database_url=SecretStr(DATABASE_URL), redis_url=SecretStr(REDIS_URL))


@pytest.mark.integration
async def test_an_org_is_created_read_back_and_found_by_no_one_else(factory):
    orgs = PgOrgs(factory)
    org = await orgs.create("SoDA", 500)
    assert await orgs.get(org.org_id) == org
    assert await orgs.get(OrgId(str(uuid4()))) is None


@pytest.mark.integration
async def test_a_role_belongs_to_one_org_and_one_platform_identity(factory):
    orgs = PgOrgs(factory)
    soda = await orgs.create("SoDA", 500)
    acm = await orgs.create("ACM", 500)
    ash = MemberRef("discord", "u1")
    await orgs.set_role(soda.org_id, ash, Role.ADMIN)
    assert await orgs.role(soda.org_id, ash) == Role.ADMIN
    assert await orgs.role(acm.org_id, ash) == Role.MEMBER
    assert await orgs.role(soda.org_id, MemberRef("slack", "u1")) == Role.MEMBER
    await orgs.set_role(soda.org_id, ash, Role.OFFICER)
    assert await orgs.role(soda.org_id, ash) == Role.OFFICER


@pytest.mark.integration
async def test_spend_accumulates_for_one_org_and_resets_for_every_org(factory):
    orgs = PgOrgs(factory)
    soda = await orgs.create("SoDA", 500)
    acm = await orgs.create("ACM", 500)
    await orgs.add_spend(soda.org_id, 1.4)
    await orgs.add_spend(soda.org_id, 2.6)
    assert (await orgs.get(soda.org_id)).spent_cents == 4
    assert (await orgs.get(acm.org_id)).spent_cents == 0
    await orgs.add_spend(acm.org_id, 10)
    await orgs.reset_spend()
    assert (await orgs.get(soda.org_id)).spent_cents == 0
    assert (await orgs.get(acm.org_id)).spent_cents == 0


@pytest.mark.integration
async def test_one_org_holds_workspaces_on_two_platforms_and_a_link_moves(factory, vault):
    orgs, workspaces = PgOrgs(factory), PgWorkspaces(factory, vault)
    soda = await orgs.create("SoDA", 500)
    acm = await orgs.create("ACM", 500)
    discord = WorkspaceRef("discord", "g1")
    await workspaces.link(
        Workspace(discord, soda.org_id, "SoDA Discord", ChannelRef(discord, "c1"))
    )
    await workspaces.link(Workspace(WorkspaceRef("slack", "T1"), soda.org_id, "SoDA Slack", None))

    found = await workspaces.get(discord)
    assert found.org_id == soda.org_id
    assert found.notice_channel == ChannelRef(discord, "c1")
    assert await workspaces.get(WorkspaceRef("slack", "g1")) is None
    assert {w.ref.platform for w in await workspaces.of_org(soda.org_id)} == {"discord", "slack"}
    assert (await workspaces.get(WorkspaceRef("slack", "T1"))).notice_channel is None

    await workspaces.link(Workspace(discord, acm.org_id, "ACM Discord", None))
    assert (await workspaces.get(discord)).org_id == acm.org_id
    assert [w.ref.platform for w in await workspaces.of_org(soda.org_id)] == ["slack"]

    await workspaces.unlink(discord)
    assert await workspaces.get(discord) is None
    assert await workspaces.of_org(acm.org_id) == []


@pytest.mark.integration
async def test_a_fact_is_replaced_by_key_forgotten_and_never_seen_by_another_org(factory):
    orgs, context = PgOrgs(factory), PgOrgContext(factory)
    soda = await orgs.create("SoDA", 500)
    acm = await orgs.create("ACM", 500)
    await context.remember(soda.org_id, OrgFact(FactCategory.ORG_INFO, "meeting", "Tuesdays 6pm"))
    await context.remember(soda.org_id, OrgFact(FactCategory.ORG_INFO, "meeting", "Fridays 4pm"))
    await context.remember(
        soda.org_id, OrgFact(FactCategory.TOOL_MAPPING, "budget", "the Finance database")
    )
    assert await context.facts(acm.org_id) == []
    assert await context.facts(soda.org_id) == [
        OrgFact(FactCategory.ORG_INFO, "meeting", "Fridays 4pm"),
        OrgFact(FactCategory.TOOL_MAPPING, "budget", "the Finance database"),
    ]
    await context.forget(acm.org_id, "meeting")
    assert len(await context.facts(soda.org_id)) == 2
    await context.forget(soda.org_id, "meeting")
    assert [f.key for f in await context.facts(soda.org_id)] == ["budget"]


@pytest.mark.integration
async def test_collaboration_state_moves_by_signals_and_never_crosses_an_org(factory):
    orgs, collaboration = PgOrgs(factory), PgCollaboration(factory)
    soda = await orgs.create("SoDA", 500)
    acm = await orgs.create("ACM", 500)
    ash = MemberRef("discord", "u1")

    assert (await collaboration.state(soda.org_id, ash)).observations == 0
    assert (await collaboration.state(soda.org_id, ash)).score(Dimension.DEPTH) == NEUTRAL

    await collaboration.observe(
        soda.org_id, ash, [Signal(Dimension.DEPTH, 0.0, Evidence.CONFIRMATION_CANCELLED)]
    )
    await collaboration.observe(
        soda.org_id, ash, [Signal(Dimension.DEPTH, 0.0, Evidence.CONFIRMATION_CANCELLED)]
    )
    twice = await collaboration.state(soda.org_id, ash)
    assert twice.observations == 2
    assert twice.score(Dimension.DEPTH) < NEUTRAL
    assert twice.score(Dimension.AUTONOMY) == NEUTRAL

    assert (await collaboration.state(acm.org_id, ash)).observations == 0
    assert (await collaboration.state(soda.org_id, MemberRef("slack", "u1"))).observations == 0

    await collaboration.forget(acm.org_id, ash)
    assert (await collaboration.state(soda.org_id, ash)).observations == 2
    await collaboration.forget(soda.org_id, ash)
    assert (await collaboration.state(soda.org_id, ash)).observations == 0


@pytest.mark.integration
async def test_a_credential_is_stored_sealed_and_read_back_opened(factory, vault):
    orgs, credentials = PgOrgs(factory), PgCredentials(factory, vault)
    soda = await orgs.create("SoDA", 500)
    acm = await orgs.create("ACM", 500)
    expires = datetime(2026, 9, 15, 18, tzinfo=UTC)
    auth = ProviderAuth(
        org_id=soda.org_id,
        provider="google",
        access_token=SecretStr("ya29.access"),
        scopes=("calendar", "drive.readonly"),
        expires_at=expires,
        refresh_token=SecretStr("1//refresh"),
    )
    await credentials.put(auth, MemberRef("discord", "u1"))

    read = await credentials.get(soda.org_id, "google")
    assert read == auth
    assert read.access_token.get_secret_value() == "ya29.access"
    assert await credentials.get(acm.org_id, "google") is None
    assert await credentials.connected(soda.org_id) == frozenset({"google"})
    assert await credentials.connected(acm.org_id) == frozenset()

    async with factory() as session:
        stored = await session.scalar(select(CredentialRow.access_token))
    assert b"ya29" not in stored


@pytest.mark.integration
async def test_a_credential_is_replaced_invalidated_and_swept_by_expiry(factory, vault):
    orgs, credentials = PgOrgs(factory), PgCredentials(factory, vault)
    soda = await orgs.create("SoDA", 500)
    soon = datetime.now(UTC) + timedelta(minutes=20)
    member = MemberRef("discord", "u1")
    await credentials.put(
        ProviderAuth(soda.org_id, "google", SecretStr("first"), (), soon, SecretStr("r1")), member
    )
    await credentials.put(
        ProviderAuth(soda.org_id, "google", SecretStr("second"), ("calendar",), soon, None), member
    )
    read = await credentials.get(soda.org_id, "google")
    assert read.access_token.get_secret_value() == "second"
    assert read.refresh_token is None

    expiring = await credentials.expiring(datetime.now(UTC) + timedelta(hours=1))
    assert [a.provider for a in expiring] == ["google"]
    assert await credentials.expiring(datetime.now(UTC)) == []

    await credentials.mark_invalid(soda.org_id, "google")
    assert await credentials.get(soda.org_id, "google") is None
    assert await credentials.connected(soda.org_id) == frozenset()
    assert await credentials.expiring(datetime.now(UTC) + timedelta(hours=1)) == []

    await credentials.put(
        ProviderAuth(soda.org_id, "google", SecretStr("third"), (), soon, None), member
    )
    assert await credentials.connected(soda.org_id) == frozenset({"google"})


@pytest.mark.integration
async def test_tool_overrides_belong_to_one_org(factory):
    orgs, config = PgOrgs(factory), PgToolConfig(factory)
    soda = await orgs.create("SoDA", 500)
    acm = await orgs.create("ACM", 500)
    await config.set(soda.org_id, OrgToolConfig("calendar", True, {"default_reminder_minutes": 15}))
    await config.set(acm.org_id, OrgToolConfig("calendar", False, {}))
    assert await config.overrides(soda.org_id) == {
        "calendar": OrgToolConfig("calendar", True, {"default_reminder_minutes": 15})
    }
    await config.set(soda.org_id, OrgToolConfig("calendar", False, {}))
    assert (await config.overrides(soda.org_id))["calendar"].enabled is False
    assert (await config.overrides(acm.org_id))["calendar"].overrides == {}


@pytest.mark.integration
async def test_every_execution_is_appended_and_a_failure_keeps_its_message(factory):
    orgs, audit = PgOrgs(factory), PgAudit(factory)
    soda = await orgs.create("SoDA", 500)
    at = datetime(2026, 9, 15, 17, tzinfo=UTC)
    await audit.append(
        AuditEntry(
            soda.org_id,
            MemberRef("discord", "u1"),
            "calendar.create_event",
            "Exec Board",
            {"start": "16:00"},
            True,
            "",
            at,
        )
    )
    await audit.append(
        AuditEntry(
            soda.org_id,
            MemberRef("discord", "u1"),
            "calendar.delete_event",
            "Exec Board",
            {},
            False,
            "the google credential expired",
            at + timedelta(minutes=1),
        )
    )
    async with factory() as session:
        rows = (await session.scalars(select(AuditRow).order_by(AuditRow.at))).all()
    assert [(r.action, r.ok, r.error) for r in rows] == [
        ("calendar.create_event", True, ""),
        ("calendar.delete_event", False, "the google credential expired"),
    ]
    assert rows[0].payload == {"start": "16:00"}


@pytest.mark.integration
async def test_a_held_call_is_taken_once_and_not_after_it_expires(factory):
    orgs, confirmations = PgOrgs(factory), PgConfirmations(factory)
    soda = await orgs.create("SoDA", 500)
    now = datetime(2026, 9, 15, 17, tzinfo=UTC)
    channel = ChannelRef(WorkspaceRef("slack", "T1"), "C1", "th1")
    pending = PendingConfirmation(
        id=str(uuid4()),
        org_id=soda.org_id,
        requested_by=MemberRef("slack", "U1"),
        channel=channel,
        call=ToolCall("call_abc", "calendar.delete_event", {"event_id": "e1"}),
        summary="Delete Exec Board Meeting",
        expires_at=now + timedelta(minutes=2),
    )
    await confirmations.put(pending)

    taken = await confirmations.take(pending.id, now)
    assert taken == pending
    assert taken.call.id == "call_abc"
    assert await confirmations.take(pending.id, now) is None

    await confirmations.put(pending)
    assert await confirmations.take(pending.id, now + timedelta(minutes=3)) is None
    assert await confirmations.take(pending.id, now) is None


@pytest.mark.integration
async def test_expired_holds_are_purged_and_live_ones_are_left(factory):
    orgs, confirmations = PgOrgs(factory), PgConfirmations(factory)
    soda = await orgs.create("SoDA", 500)
    now = datetime(2026, 9, 15, 17, tzinfo=UTC)

    def hold(name, expires):
        return PendingConfirmation(
            id=name,
            org_id=soda.org_id,
            requested_by=MemberRef("discord", "u1"),
            channel=ChannelRef(WorkspaceRef("discord", "g1"), "c1"),
            call=ToolCall(f"call_{name}", "calendar.delete_event", {}),
            summary="Delete it",
            expires_at=expires,
        )

    await confirmations.put(hold("old", now - timedelta(minutes=1)))
    await confirmations.put(hold("due", now))
    await confirmations.put(hold("live", now + timedelta(minutes=1)))
    assert await confirmations.purge_expired(now) == 2
    assert await confirmations.purge_expired(now) == 0
    assert (await confirmations.take("live", now)).id == "live"


@pytest.mark.integration
async def test_chunks_are_replaced_per_document_and_searched_within_one_org(factory):
    orgs, documents = PgOrgs(factory), PgDocuments(factory)
    soda = await orgs.create("SoDA", 500)
    acm = await orgs.create("ACM", 500)

    def chunk(org_id, source, source_id, index, txt):
        return Chunk(org_id, source, source_id, index, "Minutes", txt, {"page": index})

    await documents.replace(
        soda.org_id,
        "notion",
        "page-1",
        [chunk(soda.org_id, "notion", "page-1", 0, "we approved the budget")],
        [vector(1.0)],
    )
    await documents.replace(
        soda.org_id,
        "drive",
        "file-1",
        [chunk(soda.org_id, "drive", "file-1", 0, "unrelated")],
        [vector(0.0, 1.0)],
    )
    await documents.replace(
        acm.org_id,
        "notion",
        "page-1",
        [chunk(acm.org_id, "notion", "page-1", 0, "another org's minutes")],
        [vector(1.0)],
    )

    hits = await documents.search(soda.org_id, vector(1.0), 5, 0.5)
    assert [h.chunk.text for h in hits] == ["we approved the budget"]
    assert hits[0].similarity == pytest.approx(1.0)
    assert hits[0].chunk.metadata == {"page": 0}
    assert await documents.search(acm.org_id, vector(1.0), 5, 0.5) != hits

    everything = await documents.search(soda.org_id, vector(1.0), 5, 0.0)
    assert [h.chunk.source for h in everything] == ["notion", "drive"]
    assert [h.chunk.source for h in await documents.search(soda.org_id, vector(1.0), 1, 0.0)] == [
        "notion"
    ]
    filtered = await documents.search(soda.org_id, vector(1.0), 5, 0.0, sources=["drive"])
    assert [h.chunk.source for h in filtered] == ["drive"]
    assert await documents.search(soda.org_id, vector(1.0), 0, 0.0) == []

    await documents.replace(
        soda.org_id,
        "notion",
        "page-1",
        [chunk(soda.org_id, "notion", "page-1", 0, "we rejected the budget")],
        [vector(1.0)],
    )
    hits = await documents.search(soda.org_id, vector(1.0), 5, 0.5)
    assert [h.chunk.text for h in hits] == ["we rejected the budget"]


@pytest.mark.integration
async def test_replacing_chunks_of_another_org_or_without_embeddings_is_refused(factory):
    orgs, documents = PgOrgs(factory), PgDocuments(factory)
    soda = await orgs.create("SoDA", 500)
    acm = await orgs.create("ACM", 500)
    theirs = Chunk(acm.org_id, "notion", "page-1", 0, "Minutes", "theirs", {})
    with pytest.raises(StoreError):
        await documents.replace(soda.org_id, "notion", "page-1", [theirs], [vector(1.0)])
    mine = Chunk(soda.org_id, "notion", "page-1", 0, "Minutes", "mine", {})
    with pytest.raises(StoreError):
        await documents.replace(soda.org_id, "notion", "page-1", [mine], [])


@pytest.mark.integration
async def test_pruning_drops_one_source_and_leaves_the_others(factory):
    orgs, documents = PgOrgs(factory), PgDocuments(factory)
    soda = await orgs.create("SoDA", 500)
    await documents.replace(
        soda.org_id,
        "zoom",
        "rec-1",
        [Chunk(soda.org_id, "zoom", "rec-1", 0, "Call", "transcript", {})],
        [vector(1.0)],
    )
    await documents.replace(
        soda.org_id,
        "notion",
        "page-1",
        [Chunk(soda.org_id, "notion", "page-1", 0, "Minutes", "minutes", {})],
        [vector(1.0)],
    )
    horizon = datetime.now(UTC) + timedelta(days=1)
    assert await documents.prune("zoom", datetime.now(UTC) - timedelta(days=1)) == 0
    assert await documents.prune("zoom", horizon) == 1
    assert [h.chunk.source for h in await documents.search(soda.org_id, vector(1.0), 5, 0.0)] == [
        "notion"
    ]


@pytest.mark.integration
async def test_a_member_is_allowed_up_to_the_limit_in_one_window(data):
    limiter = RedisRateLimiter(data, RateLimit(per_member_per_minute=3))
    org = OrgId(str(uuid4()))
    ash, bo = MemberRef("discord", "u1"), MemberRef("discord", "u2")
    assert [await limiter.allow(org, ash) for _ in range(4)] == [True, True, True, False]
    assert await limiter.allow(org, bo) is True
    assert await limiter.allow(OrgId(str(uuid4())), ash) is True


@pytest.mark.integration
async def test_spend_keeps_fractions_of_a_cent(factory):
    # Whole-cent rounding would drop every call of a cheap model and never reach the budget.
    orgs = PgOrgs(factory)
    org = await orgs.create("Robotics Club", 100)
    for _ in range(4):
        await orgs.add_spend(org.org_id, 0.25)
    stored = await orgs.get(org.org_id)
    assert stored is not None
    assert stored.spent_cents == pytest.approx(1.0)


@pytest.mark.integration
async def test_jobs_leave_the_queue_in_the_order_they_arrived(data):
    org = OrgId(str(uuid4()))
    async with Redis.from_url(REDIS_URL) as client:
        await client.delete(QUEUE_KEY)
    queue = RedisQueue(data)
    assert await queue.next() is None
    await queue.enqueue(Job("sync:drive", org, {"n": 1}))
    await queue.enqueue(Job("document:notion", org, {"n": 2}))
    first = await queue.next()
    second = await queue.next()
    assert (first.kind, first.payload) == ("sync:drive", {"n": 1})
    assert (second.kind, second.payload) == ("document:notion", {"n": 2})
    assert await queue.next() is None


def test_the_committed_embedding_width_is_the_width_of_the_column():
    """pgvector fixes the width in the column type, so a drifted zipy.toml would fail at insert."""
    load_config.cache_clear()
    assert load_config().models["embedding"].dimensions == EMBEDDING_DIMENSIONS


@pytest.fixture
async def bucket(data):
    """A limiter of 60 calls a minute over a burst of 3, its key cleared."""
    limits = RateLimit(provider=ProviderRate(per_minute=60, burst=3))
    limiter = RedisProviderLimiter(data, limits)
    await limiter._redis.delete(bucket_key(BUCKET_ORG, "notion"))
    yield limiter
    await limiter._redis.delete(bucket_key(BUCKET_ORG, "notion"))
    await limiter._redis.aclose()


@pytest.mark.integration
async def test_a_burst_of_calls_goes_straight_through(bucket):
    for _ in range(3):
        await bucket.acquire(BUCKET_ORG, "notion", 0.0)


@pytest.mark.integration
async def test_a_call_past_the_burst_with_no_budget_to_wait_is_refused(bucket):
    for _ in range(3):
        await bucket.acquire(BUCKET_ORG, "notion", 0.0)
    with pytest.raises(RateLimited):
        await bucket.acquire(BUCKET_ORG, "notion", 0.0)


@pytest.mark.integration
async def test_a_call_past_the_burst_waits_for_the_refill_rather_than_failing(bucket):
    for _ in range(3):
        await bucket.acquire(BUCKET_ORG, "notion", 0.0)
    started = time.monotonic()
    await bucket.acquire(BUCKET_ORG, "notion", 5.0)
    # 60 a minute is one a second, so the fourth call comes a second after the third.
    assert 0.5 <= time.monotonic() - started <= 3.0


@pytest.mark.integration
async def test_one_org_spending_its_budget_leaves_another_orgs_alone(bucket):
    for _ in range(3):
        await bucket.acquire(BUCKET_ORG, "notion", 0.0)
    other = OrgId("bucket-org-2")
    try:
        await bucket.acquire(other, "notion", 0.0)
    finally:
        await bucket._redis.delete(bucket_key(other, "notion"))


def test_member_state_holds_no_text_so_it_cannot_come_to_hold_what_was_said():
    from sqlalchemy import String, Text

    from engine.data.tables import MemberStateRow

    keys = {"org_id", "platform", "user_id"}
    for column in MemberStateRow.__table__.columns:
        if column.name in keys:
            continue
        assert not isinstance(column.type, (Text, String)), (
            f"member_state.{column.name} can hold text. The state is what behaviour showed, "
            "never what was said; a text column makes that promise unkeepable."
        )
