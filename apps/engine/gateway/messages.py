"""What platforms hand the gateway, and what the gateway hands back."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from engine.core.types import ChannelRef, MemberRef


@dataclass(frozen=True)
class Capabilities:
    """What a platform can render. The gateway shapes outbound messages to fit."""

    markup: str
    message_limit: int
    buttons: bool
    threads: bool
    direct_messages: bool


@dataclass(frozen=True)
class Inbound:
    """A message addressed to Zipy: a mention, a direct message, or a thread reply to it."""

    channel: ChannelRef
    member: MemberRef
    display_name: str
    text: str
    direct: bool
    received_at: datetime
    platform_roles: tuple[str, ...] = ()
    #: The message of Zipy's this one replies to. Empty when it replies to nothing.
    reply_to: str = ""


class Answer(StrEnum):
    """A reply to a confirmation prompt."""

    CONFIRM = "confirm"
    CANCEL = "cancel"


@dataclass(frozen=True)
class InboundAnswer:
    """A member answering a confirmation prompt, by button or by typing."""

    channel: ChannelRef
    member: MemberRef
    confirmation_id: str
    answer: Answer
    received_at: datetime


@dataclass(frozen=True)
class WorkspaceInstalled:
    """Zipy was added to a workspace."""

    channel: ChannelRef
    installed_by: MemberRef
    name: str


@dataclass(frozen=True)
class Text:
    """Text to post, already within the platform's message limit."""

    channel: ChannelRef
    text: str
    private_to: MemberRef | None = None


@dataclass(frozen=True)
class ConfirmPrompt:
    """Ask for confirmation. Platforms without buttons show the typed answers instead."""

    channel: ChannelRef
    confirmation_id: str
    summary: str
    expires_at: datetime


Outbound = Text | ConfirmPrompt
