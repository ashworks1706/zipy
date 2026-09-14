"""The doubles behave as their protocols promise."""

from datetime import UTC, datetime, timedelta

from engine.core.doubles import MemoryConfirmations, MemoryWorkspaces
from engine.core.types import (
    ChannelRef,
    MemberRef,
    OrgId,
    PendingConfirmation,
    ToolCall,
    Workspace,
    WorkspaceRef,
)


async def test_a_confirmation_is_taken_once_and_not_after_it_expires():
    now = datetime(2026, 9, 13, tzinfo=UTC)
    store = MemoryConfirmations()
    pending = PendingConfirmation(
        "c1",
        OrgId("org-1"),
        MemberRef("slack", "U1"),
        ChannelRef(WorkspaceRef("slack", "T1"), "C1"),
        ToolCall("t", "calendar.delete_event", {}),
        "Delete Exec Board Meeting",
        now + timedelta(minutes=2),
    )
    await store.put(pending)
    assert await store.take("c1", now) == pending
    assert await store.take("c1", now) is None
    await store.put(pending)
    assert await store.take("c1", now + timedelta(minutes=3)) is None


async def test_one_org_can_hold_workspaces_on_two_platforms():
    store = MemoryWorkspaces()
    org = OrgId("org-1")
    await store.link(Workspace(WorkspaceRef("discord", "g1"), org, "SoDA Discord", None))
    await store.link(Workspace(WorkspaceRef("slack", "T1"), org, "SoDA Slack", None))
    assert {w.ref.platform for w in await store.of_org(org)} == {"discord", "slack"}
    assert await store.get(WorkspaceRef("slack", "g1")) is None
