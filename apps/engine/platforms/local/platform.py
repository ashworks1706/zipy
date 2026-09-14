"""The local platform: one conversation in a terminal, as plain text or JSON lines.

Its workspace is local, its member is the developer at the keyboard with the admin role, and its
org is created on first run. Confirmations are answered by typing, or by the console's keys.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from engine.core.types import ChannelRef, ChatMessage
from engine.gateway.messages import Capabilities, Outbound
from engine.platforms.base import BasePlatform


class LocalSettings(BaseModel):
    """[platforms.local] settings."""

    model_config = ConfigDict(extra="forbid")

    jsonl: bool = False
    org_name: str = "Local dev org"
    member_name: str = "developer"
    message_limit: int = 100_000


class LocalPlatform(BasePlatform[LocalSettings]):
    """Reads stdin, writes stdout. Keeps its own conversation in memory for recent()."""

    name: ClassVar[str] = "local"
    settings_model: ClassVar[type[BaseModel]] = LocalSettings

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            markup="markdown",
            message_limit=self.settings.message_limit,
            buttons=self.settings.jsonl,
            threads=False,
            direct_messages=True,
        )

    async def run(self) -> None:
        """Read lines until stdin closes; each ask goes to the gateway, each reply is written."""
        raise NotImplementedError

    async def send(self, outbound: Outbound) -> None:
        raise NotImplementedError

    async def recent(self, channel: ChannelRef, limit: int) -> list[ChatMessage]:
        raise NotImplementedError
