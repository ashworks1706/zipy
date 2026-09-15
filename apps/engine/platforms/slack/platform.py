"""The slack platform.

Events, their signature and Block Kit rendering are here. Posting a message, reading a
conversation and the per-workspace OAuth install need the Slack SDK and a sealed bot token, which
this Zipy does not have yet, so those calls say so instead of half working. See ROADMAP v0.5.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, ClassVar

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, SecretStr

from engine.core.types import ChannelRef, ChatMessage, MemberRef, PlatformError, WorkspaceRef
from engine.gateway.messages import Capabilities, Inbound, InboundAnswer, Outbound
from engine.platforms.base import BasePlatform
from engine.platforms.slack.render import ACTIONS

VERSION = "v0"
SIGNATURE_WINDOW_SECS = 300
MISSING_SDK = "slack needs the slack sdk and a workspace bot token, see docs/ROADMAP.md v0.5"


class SlackSettings(BaseModel):
    """[platforms.slack] settings. Secrets are in .env."""

    model_config = ConfigDict(extra="forbid")

    client_id: str = ""
    client_secret: SecretStr = SecretStr("")
    signing_secret: SecretStr = SecretStr("")
    message_limit: int = 3000


def signature(signing_secret: str, timestamp: str, body: bytes) -> str:
    """The signature Slack sends for this request body."""
    base = b"%s:%s:%s" % (VERSION.encode(), timestamp.encode(), body)
    digest = hmac.new(signing_secret.encode(), base, hashlib.sha256).hexdigest()
    return f"{VERSION}={digest}"


def verified(
    signing_secret: str,
    timestamp: str,
    body: bytes,
    sent: str,
    now: datetime,
) -> bool:
    """Whether a request carries Slack's signature and a timestamp within the window."""
    try:
        age = abs(now.timestamp() - float(timestamp))
    except ValueError:
        return False
    if age > SIGNATURE_WINDOW_SECS:
        return False
    return hmac.compare_digest(signature(signing_secret, timestamp, body), sent)


def event_time(raw: object) -> datetime:
    """The moment a Slack ts names."""
    try:
        return datetime.fromtimestamp(float(str(raw)), UTC)
    except ValueError as exc:
        raise PlatformError(f"slack event has no usable timestamp: {raw!r}") from exc


def strip_mention(text: str, bot_user: str) -> str:
    """The message text without the mention that addressed Zipy."""
    return " ".join(text.replace(f"<@{bot_user}>", " ").split()) if bot_user else text.strip()


def bot_user_of(payload: Mapping[str, Any]) -> str:
    """The Zipy user id the event was delivered for, empty when the payload names none."""
    authorizations = payload.get("authorizations")
    if isinstance(authorizations, list) and authorizations:
        first = authorizations[0]
        if isinstance(first, dict):
            return str(first.get("user_id", ""))
    return ""


def inbound_from(payload: Mapping[str, Any]) -> Inbound | None:
    """The Inbound an Events API callback carries, or None when Zipy is not addressed."""
    if payload.get("type") != "event_callback":
        return None
    event = payload.get("event")
    if not isinstance(event, dict) or event.get("bot_id") or event.get("subtype"):
        return None
    direct = event.get("channel_type") == "im"
    if event.get("type") != "app_mention" and not direct:
        return None
    user, channel = str(event.get("user", "")), str(event.get("channel", ""))
    team = str(payload.get("team_id", ""))
    if not user or not channel or not team:
        return None
    thread = str(event.get("thread_ts", ""))
    return Inbound(
        channel=ChannelRef(
            workspace=WorkspaceRef(platform="slack", workspace_id=team),
            channel_id=channel,
            thread_id="" if thread == str(event.get("ts", "")) else thread,
        ),
        member=MemberRef(platform="slack", user_id=user),
        display_name=user,
        text=strip_mention(str(event.get("text", "")), bot_user_of(payload)),
        direct=bool(direct),
        received_at=event_time(event.get("ts")),
    )


def answer_from(payload: Mapping[str, Any]) -> InboundAnswer | None:
    """The InboundAnswer a Block Kit button carries, or None when it is not Zipy's."""
    if payload.get("type") != "block_actions":
        return None
    actions = payload.get("actions")
    if not isinstance(actions, list) or not actions or not isinstance(actions[0], dict):
        return None
    action = actions[0]
    answer = ACTIONS.get(str(action.get("action_id", "")))
    confirmation_id = str(action.get("value", ""))
    if answer is None or not confirmation_id:
        return None
    team = _identifier(payload.get("team"))
    channel = _identifier(payload.get("channel"))
    user = _identifier(payload.get("user"))
    if not team or not channel or not user:
        return None
    return InboundAnswer(
        channel=ChannelRef(
            workspace=WorkspaceRef(platform="slack", workspace_id=team),
            channel_id=channel,
            thread_id=str(payload.get("thread_ts", "")),
        ),
        member=MemberRef(platform="slack", user_id=user),
        confirmation_id=confirmation_id,
        answer=answer,
        received_at=event_time(action.get("action_ts")),
    )


def _identifier(part: object) -> str:
    return str(part.get("id", "")) if isinstance(part, dict) else ""


class SlackPlatform(BasePlatform[SlackSettings]):
    """Slack over the Events API, installed per workspace by OAuth. A mention or DM reaches Zipy."""

    name: ClassVar[str] = "slack"
    owns: ClassVar[tuple[str, ...]] = ()
    settings_model: ClassVar[type[BaseModel]] = SlackSettings

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            markup="slack-mrkdwn",
            message_limit=self.settings.message_limit,
            buttons=True,
            threads=True,
            direct_messages=True,
        )

    def verify(self, timestamp: str, body: bytes, sent: str, now: datetime) -> bool:
        """Whether a request to this platform's routes came from Slack."""
        secret = self.settings.signing_secret.get_secret_value()
        if not secret:
            raise PlatformError(
                "platforms.slack has no signing secret; set ZIPY_PLATFORMS__SLACK__SIGNING_SECRET"
            )
        return verified(secret, timestamp, body, sent, now)

    async def run(self) -> None:
        """Slack receives over HTTP; there is no outward connection to hold."""
        raise PlatformError(MISSING_SDK)

    async def send(self, outbound: Outbound) -> None:
        raise PlatformError(f"{MISSING_SDK}: nothing was posted to {outbound.channel.channel_id}")

    async def recent(self, channel: ChannelRef, limit: int) -> list[ChatMessage]:
        raise PlatformError(f"{MISSING_SDK}: {limit} messages of {channel.channel_id} unread")

    def router(self) -> APIRouter | None:
        """No routes: events Zipy cannot answer are not accepted."""
        return None
