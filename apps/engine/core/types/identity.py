"""Who and where, independent of any chat platform.

An org is Zipy's tenant. A workspace is one place on one platform (a Discord server, a Slack
workspace) linked to an org. Platform, workspace, channel and user ids are the platform's own
strings; Zipy never interprets them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, NewType

if TYPE_CHECKING:
    from engine.core.types.chat import Attachment
    from engine.core.types.progress import Progress

OrgId = NewType("OrgId", str)


class Role(StrEnum):
    """What a member may do in an org. An unregistered member is a member."""

    ADMIN = "admin"
    OFFICER = "officer"
    MEMBER = "member"


@dataclass(frozen=True)
class WorkspaceRef:
    """One workspace on one platform."""

    platform: str
    workspace_id: str


@dataclass(frozen=True)
class ChannelRef:
    """One conversation: a channel, and a thread in it when the platform has threads."""

    workspace: WorkspaceRef
    channel_id: str
    thread_id: str = ""

    @property
    def platform(self) -> str:
        return self.workspace.platform


@dataclass(frozen=True)
class MemberRef:
    """One person on one platform."""

    platform: str
    user_id: str


@dataclass(frozen=True)
class RequestContext:
    """Who asked, where, and under which org. Nothing runs without one."""

    org_id: OrgId
    channel: ChannelRef
    member: MemberRef
    role: Role
    display_name: str
    request_id: str
    received_at: datetime
    #: The message of Zipy's this one replies to. Empty when it replies to nothing.
    reply_to: str = ""
    #: Images attached to the member's message.
    images: tuple[Attachment, ...] = ()
    #: Files attached to the member's message, read into text rather than sent as images.
    files: tuple[Attachment, ...] = ()
    #: How far inside delegation this is running. 0 is the request, 1 is a sub-agent.
    depth: int = 0
    #: The delegate call a sub-agent is running under. Empty at depth 0.
    parent: str = ""
    #: Where live progress goes while this request runs. None when nobody is watching.
    #: Excluded from equality: two contexts differing only in who is watching are the same request.
    watcher: Callable[[Progress], None] | None = field(default=None, compare=False)
