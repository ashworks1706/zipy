"""BaseProvider: the OAuth flow and webhook verification of one account type."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import ClassVar

from pydantic import BaseModel

from engine.core.types import Job, OrgId, ProviderAuth


class BaseProvider[S: BaseModel](ABC):
    """One account type. name matches its folder and its [providers.name] table."""

    name: ClassVar[str]
    owns: ClassVar[tuple[str, ...]] = ()
    settings_model: ClassVar[type[BaseModel]]

    def __init__(self, settings: S, redirect_url: str) -> None:
        self.settings = settings
        self.redirect_url = redirect_url

    @abstractmethod
    def authorize_url(self, state: str, scopes: list[str]) -> str:
        """Where the admin is sent to grant access."""

    @abstractmethod
    async def exchange(self, org_id: OrgId, code: str) -> ProviderAuth:
        """Tokens for an authorization code."""

    @abstractmethod
    async def refresh(self, auth: ProviderAuth) -> ProviderAuth:
        """New tokens for an expiring credential. A revoked grant is an OAuthError."""

    async def webhook(
        self,
        headers: Mapping[str, str],  # noqa: ARG002 - overridable hook
        body: bytes,  # noqa: ARG002 - overridable hook
    ) -> Job | None:
        """The job a verified webhook asks for, or None. A bad signature is an OAuthError."""
        return None
