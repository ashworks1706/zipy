"""BasePlatform: what every chat platform plugin implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from fastapi import APIRouter
from pydantic import BaseModel

from engine.core.types import ChannelRef, ChatMessage
from engine.gateway.gateway import Gateway
from engine.gateway.messages import Capabilities, Outbound


class BasePlatform[S: BaseModel](ABC):
    """One chat platform. name matches its folder and its [platforms.name] table.

    owns lists the third-party libraries only this plugin may import.
    """

    name: ClassVar[str]
    owns: ClassVar[tuple[str, ...]] = ()
    settings_model: ClassVar[type[BaseModel]]

    def __init__(self, settings: S, gateway: Gateway) -> None:
        self.settings = settings
        self.gateway = gateway

    @property
    @abstractmethod
    def capabilities(self) -> Capabilities:
        """What this platform renders, from its settings."""

    @abstractmethod
    async def run(self) -> None:
        """Connect and deliver events to the gateway until cancelled."""

    @abstractmethod
    async def send(self, outbound: Outbound) -> None:
        """Post one outbound message."""

    @abstractmethod
    async def recent(self, channel: ChannelRef, limit: int) -> list[ChatMessage]:
        """The last limit messages of a conversation, oldest first, Zipy's own as assistant."""

    def router(self) -> APIRouter | None:
        """Routes this platform receives events or installs on, mounted at /platforms/name."""
        return None
