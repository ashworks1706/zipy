"""The notion provider."""

from __future__ import annotations

import re
from typing import Any, ClassVar
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, ConfigDict, SecretStr

from engine.auth.providers.base import BaseProvider
from engine.core.types import OAuthError, OrgId, ProviderAuth

AUTHORIZE_URL = "https://api.notion.com/v1/oauth/authorize"
TOKEN_URL = "https://api.notion.com/v1/oauth/token"

# Seconds a token request may take before it is an OAuthError.
TIMEOUT_SECS = 30.0

# The OAuth error codes a failure message may repeat from the provider.
ERROR_CODE = re.compile(r"[a-z_]{1,64}")


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

    def authorize_url(
        self,
        state: str,
        scopes: list[str],  # noqa: ARG002 - notion grants the capabilities of the integration
    ) -> str:
        """Where the admin is sent to grant access."""
        query = urlencode(
            {
                "client_id": self._client_id(),
                "redirect_uri": self.redirect_url,
                "response_type": "code",
                "owner": "user",
                "state": state,
            }
        )
        return f"{AUTHORIZE_URL}?{query}"

    async def exchange(self, org_id: OrgId, code: str) -> ProviderAuth:
        """Tokens for an authorization code."""
        payload = await self._token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_url,
            }
        )
        access = payload.get("access_token")
        if not isinstance(access, str) or not access:
            raise OAuthError("notion returned no access token")
        return ProviderAuth(
            org_id=org_id,
            provider=self.name,
            access_token=SecretStr(access),
            scopes=(),
            expires_at=None,
            refresh_token=None,
        )

    async def refresh(self, auth: ProviderAuth) -> ProviderAuth:
        """New tokens for an expiring credential. A revoked grant is an OAuthError."""
        raise OAuthError(
            f"notion grants do not expire; reconnect notion for org {auth.org_id} instead"
        )

    def _client_id(self) -> str:
        if not self.settings.client_id:
            raise OAuthError("providers.notion.client_id is not set")
        return self.settings.client_id

    def _client_secret(self) -> str:
        secret = self.settings.client_secret.get_secret_value()
        if not secret:
            raise OAuthError("providers.notion.client_secret is not set")
        return secret

    async def _token(self, body: dict[str, str]) -> dict[str, Any]:
        """The parsed token response. A transport or provider failure is an OAuthError."""
        credentials = (self._client_id(), self._client_secret())
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECS) as client:
                response = await client.post(TOKEN_URL, json=body, auth=credentials)
        except httpx.HTTPError as exc:
            raise OAuthError(f"notion could not be reached: {type(exc).__name__}") from exc
        if response.is_error:
            raise OAuthError(f"notion rejected the token request: {_reason(response)}")
        try:
            parsed = response.json()
        except ValueError as exc:
            raise OAuthError("notion returned a token response that is not json") from exc
        if not isinstance(parsed, dict):
            raise OAuthError("notion returned a token response that is not an object")
        return parsed


def _reason(response: httpx.Response) -> str:
    """The failure as a status and the OAuth error code, never the response body."""
    try:
        parsed = response.json()
    except ValueError:
        parsed = None
    code = parsed.get("error") if isinstance(parsed, dict) else None
    named = f" {code}" if isinstance(code, str) and ERROR_CODE.fullmatch(code) else ""
    return f"HTTP {response.status_code}{named}"
