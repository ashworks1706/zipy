"""The slack platform."""

from __future__ import annotations

from typing import ClassVar

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, SecretStr

from engine.core.types import ChannelRef, ChatMessage
from engine.gateway.messages import Capabilities, Outbound
from engine.platforms.base import BasePlatform


class SlackSettings(BaseModel):
    """[platforms.slack] settings. Secrets are in .env."""

    model_config = ConfigDict(extra="forbid")

    client_id: str = ""
    client_secret: SecretStr = SecretStr("")
    signing_secret: SecretStr = SecretStr("")
    message_limit: int = 3000


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

    async def run(self) -> None:
        raise NotImplementedError

    async def send(self, outbound: Outbound) -> None:
        raise NotImplementedError

    async def recent(self, channel: ChannelRef, limit: int) -> list[ChatMessage]:
        raise NotImplementedError

    def router(self) -> APIRouter | None:
        """Event, interaction and install routes, verified with signing_secret."""
        raise NotImplementedError
