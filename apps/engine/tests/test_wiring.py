"""The composition root: the object graph builds, and the seams between its parts agree."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet

from engine.auth.state import ConnectState, sign, verify
from engine.core.config import Config, load
from engine.core.types import ChannelRef, ConfigError, MemberRef, OrgId, WorkspaceRef
from engine.wiring import (
    Conversations,
    assemble,
    provider_scopes,
    routers,
    selected,
    system_template,
)


@pytest.fixture
def wired(monkeypatch, cfg: Config) -> Config:
    """The committed zipy.toml with the per-machine secrets a build needs."""
    monkeypatch.setenv("ZIPY_DATA__DATABASE_URL", "postgresql+asyncpg://zipy@127.0.0.1/zipy")
    monkeypatch.setenv("ZIPY_DATA__REDIS_URL", "redis://127.0.0.1:6379/0")
    monkeypatch.setenv("ZIPY_DATA__FERNET_KEY", Fernet.generate_key().decode())
    load.cache_clear()
    return Config(_env_file=None)


def test_the_whole_object_graph_builds_from_the_committed_config(wired):
    parts = assemble(wired)
    assert sorted(parts.platforms.enabled) == ["local"]
    assert parts.providers is not None
    assert parts.scheduler is not None
    assert parts.consumer is not None
    assert routers(parts.platforms) == {}, "discord connects outward and serves no route"


def test_a_connect_link_the_gateway_signs_verifies_at_the_callback(wired):
    # The gateway signs with data.fernet_key; wiring must hand the callback the same key or every
    # connect link fails verification at the moment a user clicks it.
    parts = assemble(wired)
    key = wired.data.fernet_key
    state = ConnectState(
        org_id=OrgId("org-1"),
        member=MemberRef("discord", "u1"),
        provider="google",
        issued_at=datetime.now(UTC),
    )
    token = sign(state, key)
    assert verify(token, parts.oauth._state_key, datetime.now(UTC), 900).org_id == state.org_id


def test_only_builds_the_named_platforms_whatever_the_config_says(wired):
    tables = selected(wired, ["local"])
    assert [name for name, table in tables.items() if table.enabled] == ["local"]
    assert assemble(wired, ["local"]).platforms.enabled.keys() == {"local"}


def test_an_unknown_platform_name_is_refused(wired):
    with pytest.raises(ConfigError, match="teams"):
        selected(wired, ["teams"])


def test_a_provider_is_asked_for_the_scopes_of_its_enabled_tools(wired):
    scopes = provider_scopes(wired)
    calendar = wired.tools["calendar"]
    assert calendar.provider == "google"
    for scope in calendar.scopes:
        assert scope in scopes["google"]
    assert scopes["google"] == sorted(set(scopes["google"]), key=scopes["google"].index)


def test_a_disabled_tool_does_not_widen_the_scopes_it_asks_for(wired):
    off = {name: table.model_copy(update={"enabled": False}) for name, table in wired.tools.items()}
    narrowed = provider_scopes(wired.model_copy(update={"tools": off}))
    assert all(not asked for asked in narrowed.values())


def test_a_missing_system_template_is_named(wired):
    with pytest.raises(ConfigError, match="nope.md.j2"):
        system_template("nope.md.j2")
    assert "running operations for" in system_template(wired.agent.system_template)


async def test_the_conversation_source_refuses_to_read_before_it_is_bound():
    source = Conversations()
    channel = ChannelRef(WorkspaceRef("discord", "g1"), "c1")
    with pytest.raises(ConfigError, match="before the platforms"):
        await source.recent(channel, 10)
