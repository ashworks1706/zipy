"""Messages to and from the model, tool calls, and what the agent hands back to the gateway."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from engine.core.types.identity import ChannelRef, MemberRef, OrgId


class Speaker(StrEnum):
    """The role of a chat message in the model's message array."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ActionType(StrEnum):
    """How a tool action runs. Set in zipy.toml per action, never by the model."""

    READ = "read"
    CREATE = "create"
    DESTRUCTIVE = "destructive"


@dataclass(frozen=True)
class ToolCall:
    """One call the model asked for. name is qualified: calendar.create_event."""

    id: str
    name: str
    arguments: dict[str, Any]


def wire_name(qualified_name: str) -> str:
    """The function name sent to the model, which may not contain a dot."""
    return qualified_name.replace(".", "__")


def from_wire(name: str) -> str:
    """The qualified name of a function name the model called."""
    return name.replace("__", ".", 1)


#: Media types a model is sent as an image. Anything else is dropped rather than guessed at.
IMAGE_MEDIA_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp")

#: Media types read into text. memory/ingest/parsers holds one parser per entry.
FILE_MEDIA_TYPES = (
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/json",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/zip",
    "application/x-zip-compressed",
)


@dataclass(frozen=True)
class Attachment:
    """One file attached to a member's message.

    An image reaches the model as a link, not as bytes: the platform holds them and every
    OpenAI-compatible server fetches a URL. A server with no route to the host sees no image.
    Every other type is downloaded and read into text instead.
    """

    url: str
    media_type: str
    name: str = ""
    #: What the platform said it weighs. Zero when it said nothing.
    size: int = 0

    @property
    def is_image(self) -> bool:
        """Whether this one goes to the model as an image rather than being read."""
        return self.media_type in IMAGE_MEDIA_TYPES

    @classmethod
    def of(cls, url: str, media_type: str, name: str = "", size: int = 0) -> Attachment | None:
        """An attachment, or None when nothing here handles the media type."""
        kind = media_type.split(";")[0].strip().lower()
        if not url or kind not in IMAGE_MEDIA_TYPES + FILE_MEDIA_TYPES:
            return None
        return cls(url=url, media_type=kind, name=name, size=size)

    @classmethod
    def accepted(cls, images: Sequence[Attachment], most: int) -> tuple[Attachment, ...]:
        """The images a model is sent, at most most of them."""
        kept = (cls.of(i.url, i.media_type, i.name, i.size) for i in images)
        return tuple(i for i in kept if i is not None and i.is_image)[:most]

    @classmethod
    def readable(cls, attached: Sequence[Attachment], most: int) -> tuple[Attachment, ...]:
        """The files read into text, at most most of them."""
        kept = (cls.of(f.url, f.media_type, f.name, f.size) for f in attached)
        return tuple(f for f in kept if f is not None and not f.is_image)[:most]


@dataclass(frozen=True)
class ChatMessage:
    """One message in the model's message array."""

    speaker: Speaker
    content: str
    name: str = ""
    at: datetime | None = None
    tool_call_id: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    #: Images attached to a user turn. Never stored: the links a platform issues expire.
    images: tuple[Attachment, ...] = ()


@dataclass(frozen=True)
class Usage:
    """Tokens and cost of one model call."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_cents: float = 0.0


@dataclass(frozen=True)
class Completion:
    """One model response: text, tool calls, or both."""

    text: str
    tool_calls: tuple[ToolCall, ...] = ()
    usage: Usage = field(default_factory=Usage)


@dataclass(frozen=True)
class ToolOutcome:
    """The result of one executed tool call, as the model sees it."""

    call: ToolCall
    ok: bool
    content: str


@dataclass(frozen=True)
class PendingConfirmation:
    """A destructive call waiting for an answer from someone allowed to give it."""

    id: str
    org_id: OrgId
    requested_by: MemberRef
    channel: ChannelRef
    call: ToolCall
    summary: str
    expires_at: datetime


@dataclass(frozen=True)
class AgentReply:
    """The agent finished: text to post."""

    text: str
    usage: Usage = field(default_factory=Usage)


@dataclass(frozen=True)
class NeedsConfirmation:
    """The agent stopped at a destructive call; the gateway asks, then resumes it."""

    pending: PendingConfirmation


AgentResult = AgentReply | NeedsConfirmation
