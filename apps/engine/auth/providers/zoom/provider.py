"""The zoom provider."""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, SecretStr

from engine.auth.providers.base import BaseProvider
from engine.core.types import Job, OrgId, ProviderAuth


class ZoomSettings(BaseModel):
    """[providers.zoom] settings. The client id and secret are in .env."""

    model_config = ConfigDict(extra="forbid")

    client_id: str = ""
    client_secret: SecretStr = SecretStr("")
    webhook_secret: SecretStr = SecretStr("")


class ZoomProvider(BaseProvider[ZoomSettings]):
    """Zoom OAuth, and the verified recording.completed webhook."""

    name: ClassVar[str] = "zoom"
    owns: ClassVar[tuple[str, ...]] = ()
    settings_model: ClassVar[type[BaseModel]] = ZoomSettings

    def authorize_url(self, state: str, scopes: list[str]) -> str:
        raise NotImplementedError

    async def exchange(self, org_id: OrgId, code: str) -> ProviderAuth:
        raise NotImplementedError

    async def refresh(self, auth: ProviderAuth) -> ProviderAuth:
        raise NotImplementedError

    async def webhook(self, headers: Mapping[str, str], body: bytes) -> Job | None:
        """An ingestion job for recording.completed after the signature verifies."""
        raise NotImplementedError
