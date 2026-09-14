"""The notion provider."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, SecretStr

from engine.auth.providers.base import BaseProvider
from engine.core.types import OrgId, ProviderAuth


class NotionSettings(BaseModel):
    """[providers.notion] settings. The client id and secret are in .env."""

    model_config = ConfigDict(extra="forbid")

    client_id: str = ""
    client_secret: SecretStr = SecretStr("")


class NotionProvider(BaseProvider[NotionSettings]):
    """Notion OAuth: a workspace-level grant. Notion tokens do not expire."""

    name: ClassVar[str] = "notion"
    owns: ClassVar[tuple[str, ...]] = ()
    settings_model: ClassVar[type[BaseModel]] = NotionSettings

    def authorize_url(self, state: str, scopes: list[str]) -> str:
        raise NotImplementedError

    async def exchange(self, org_id: OrgId, code: str) -> ProviderAuth:
        raise NotImplementedError

    async def refresh(self, auth: ProviderAuth) -> ProviderAuth:
        raise NotImplementedError
