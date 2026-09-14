"""The discord platform."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, SecretStr

from engine.core.types import ChannelRef, ChatMessage
from engine.gateway.messages import Capabilities, Outbound
from engine.platforms.base import BasePlatform


class DiscordSettings(BaseModel):
    """[platforms.discord] settings. Secrets are in .env."""

    model_config = ConfigDict(extra="forbid")

    token: SecretStr = SecretStr("")
    message_limit: int = 2000


class DiscordPlatform(BasePlatform[DiscordSettings]):
    """Discord over the gateway websocket. A server is a workspace; mentions and DMs reach Zipy."""

    name: ClassVar[str] = "discord"
    owns: ClassVar[tuple[str, ...]] = ("discord",)
    settings_model: ClassVar[type[BaseModel]] = DiscordSettings

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            markup="discord-markdown",
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
