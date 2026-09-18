"""Shared fixtures: the repo's zipy.toml and a request context."""

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from engine.core.config import Config, load
from engine.core.types import ChannelRef, MemberRef, OrgId, RequestContext, Role, WorkspaceRef

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _no_ambient_config(monkeypatch) -> None:
    """Hide the developer's own ZIPY_ variables.

    Running Zipy locally means exporting .env, and a test that read it would pass or fail by
    what happens to be in the shell.
    """
    for name in list(os.environ):
        if name.startswith("ZIPY_"):
            monkeypatch.delenv(name, raising=False)


@pytest.fixture
def cfg(monkeypatch) -> Config:
    monkeypatch.setenv("ZIPY_CONFIG_FILE", str(ROOT / "zipy.toml"))
    load.cache_clear()
    return Config(_env_file=None)


@pytest.fixture
def ctx() -> RequestContext:
    return RequestContext(
        org_id=OrgId("org-1"),
        channel=ChannelRef(WorkspaceRef("discord", "g1"), "c1"),
        member=MemberRef("discord", "u1"),
        role=Role.OFFICER,
        display_name="Ash",
        request_id="req-1",
        received_at=datetime(2026, 9, 13, tzinfo=UTC),
    )
