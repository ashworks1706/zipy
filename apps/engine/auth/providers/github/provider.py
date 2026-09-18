"""The github provider."""

from __future__ import annotations

import re
from typing import Any, ClassVar
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, ConfigDict, SecretStr

from engine.auth.providers.base import BaseProvider
from engine.core.types import OAuthError, OrgId, ProviderAuth

AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"

# Seconds a token request may take before it is an OAuthError.
TIMEOUT_SECS = 30.0

# The OAuth error codes a failure message may repeat from the provider.
ERROR_CODE = re.compile(r"[a-z_]{1,64}")


class GithubSettings(BaseModel):
    """[providers.github] settings. The client id and secret are in .env."""

    model_config = ConfigDict(extra="forbid")

    client_id: str = ""
    client_secret: SecretStr = SecretStr("")


class GithubProvider(BaseProvider[GithubSettings]):
    """GitHub OAuth. An OAuth app token does not expire and has no refresh token."""

    name: ClassVar[str] = "github"
    owns: ClassVar[tuple[str, ...]] = ()
    settings_model: ClassVar[type[BaseModel]] = GithubSettings

    def authorize_url(self, state: str, scopes: list[str]) -> str:
        """Where the admin is sent to grant access."""
        query = urlencode(
            {
                "client_id": self._client_id(),
                "redirect_uri": self.redirect_url,
                "scope": " ".join(scopes),
                "state": state,
            }
        )
        return f"{AUTHORIZE_URL}?{query}"

    async def exchange(self, org_id: OrgId, code: str) -> ProviderAuth:
        """Tokens for an authorization code."""
        payload = await self._token(
            {
                "client_id": self._client_id(),
                "client_secret": self._client_secret(),
                "code": code,
                "redirect_uri": self.redirect_url,
            }
        )
        access = payload.get("access_token")
        if not isinstance(access, str) or not access:
            raise OAuthError("github returned no access token")
        granted = payload.get("scope")
        return ProviderAuth(
            org_id=org_id,
            provider=self.name,
            access_token=SecretStr(access),
            scopes=tuple(granted.split(",")) if isinstance(granted, str) and granted else (),
            expires_at=None,
            refresh_token=None,
        )

    async def refresh(self, auth: ProviderAuth) -> ProviderAuth:
        """New tokens for an expiring credential. A revoked grant is an OAuthError."""
        raise OAuthError(
            f"github oauth app tokens do not expire; reconnect github for org {auth.org_id} instead"
        )

    def _client_id(self) -> str:
        if not self.settings.client_id:
            raise OAuthError("providers.github.client_id is not set")
        return self.settings.client_id

    def _client_secret(self) -> str:
        secret = self.settings.client_secret.get_secret_value()
        if not secret:
            raise OAuthError("providers.github.client_secret is not set")
        return secret

    async def _token(self, body: dict[str, str]) -> dict[str, Any]:
        """The parsed token response. A transport or provider failure is an OAuthError."""
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECS) as client:
                response = await client.post(
                    TOKEN_URL, data=body, headers={"Accept": "application/json"}
                )
        except httpx.HTTPError as exc:
            raise OAuthError(f"github could not be reached: {type(exc).__name__}") from exc
        if response.is_error:
            raise OAuthError(f"github rejected the token request: {_reason(response)}")
        try:
            parsed = response.json()
        except ValueError as exc:
            raise OAuthError("github returned a token response that is not json") from exc
        if not isinstance(parsed, dict):
            raise OAuthError("github returned a token response that is not an object")
        if parsed.get("error"):
            raise OAuthError(f"github rejected the token request: {_reason(response)}")
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
