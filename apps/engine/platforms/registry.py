"""Discovers platform plugins, builds the enabled ones, and routes by platform name.

Platforms implements ConversationSource and Notifier for the rest of the engine, dispatching each
call to the platform the conversation or workspace belongs to.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from engine.core.config import PlatformSettings
from engine.core.plugins import discover, match
from engine.core.protocols import WorkspaceStore
from engine.core.types import ChannelRef, ChatMessage, ConfigError, OrgId
from engine.gateway.gateway import Gateway
from engine.platforms.base import BasePlatform

PlatformClass = type[BasePlatform[Any]]


def platform_classes() -> dict[str, PlatformClass]:
    """Every platform plugin, by name."""
    return discover("engine.platforms", "platform", BasePlatform)


def check(tables: Mapping[str, PlatformSettings], classes: Mapping[str, PlatformClass]) -> None:
    """Fail unless plugins and tables match and every enabled table validates."""
    match("platforms", classes, tables)
    for name, cls in classes.items():
        if tables[name].enabled:
            try:
                cls.settings_model.model_validate(tables[name].options)
            except ValidationError as exc:
                raise ConfigError(f"platforms.{name} settings are invalid: {exc}") from exc


class Platforms:
    """The enabled platforms of this process."""

    def __init__(
        self,
        tables: Mapping[str, PlatformSettings],
        gateway: Gateway,
        workspaces: WorkspaceStore,
        classes: Mapping[str, PlatformClass] | None = None,
    ) -> None:
        found = dict(platform_classes() if classes is None else classes)
        check(tables, found)
        self._workspaces = workspaces
        self.enabled: dict[str, BasePlatform[Any]] = {
            name: cls(cls.settings_model.model_validate(tables[name].options), gateway)
            for name, cls in found.items()
            if tables[name].enabled
        }

    def get(self, name: str) -> BasePlatform[Any]:
        """One enabled platform. Unknown or disabled is a ConfigError."""
        if name not in self.enabled:
            raise ConfigError(f"platform {name} is not enabled")
        return self.enabled[name]

    async def recent(self, channel: ChannelRef, limit: int) -> list[ChatMessage]:
        """ConversationSource, from the platform the channel belongs to."""
        return await self.get(channel.platform).recent(channel, limit)

    async def notify(self, org_id: OrgId, text: str) -> None:
        """Notifier: post to the notice channel of every enabled workspace of the org."""
        raise NotImplementedError
