"""Messages to and from the model, tool calls, and what the agent hands back to the gateway."""

from __future__ import annotations

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


@dataclass(frozen=True)
class ChatMessage:
    """One message in the model's message array."""

    speaker: Speaker
    content: str
    name: str = ""
    at: datetime | None = None
    tool_call_id: str = ""
    tool_calls: tuple[ToolCall, ...] = ()


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
