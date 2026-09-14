"""The google provider."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, SecretStr

from engine.auth.providers.base import BaseProvider
from engine.core.types import OrgId, ProviderAuth


class GoogleSettings(BaseModel):
    """[providers.google] settings. The client id and secret are in .env."""

    model_config = ConfigDict(extra="forbid")

    client_id: str = ""
    client_secret: SecretStr = SecretStr("")


class GoogleProvider(BaseProvider[GoogleSettings]):
    """Google OAuth: one grant covers every Google tool, with offline access for refresh."""

    name: ClassVar[str] = "google"
    owns: ClassVar[tuple[str, ...]] = ()
    settings_model: ClassVar[type[BaseModel]] = GoogleSettings

    def authorize_url(self, state: str, scopes: list[str]) -> str:
        raise NotImplementedError

    async def exchange(self, org_id: OrgId, code: str) -> ProviderAuth:
        raise NotImplementedError

    async def refresh(self, auth: ProviderAuth) -> ProviderAuth:
        raise NotImplementedError
