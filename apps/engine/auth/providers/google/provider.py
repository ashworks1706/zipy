"""The google provider."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, ConfigDict, SecretStr

from engine.auth.providers.base import BaseProvider
from engine.core.types import OAuthError, OrgId, ProviderAuth

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"

# Seconds a token request may take before it is an OAuthError.
TIMEOUT_SECS = 30.0

# The OAuth error codes a failure message may repeat from the provider.
ERROR_CODE = re.compile(r"[a-z_]{1,64}")


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
        """Where the admin is sent to grant access."""
        if not scopes:
            raise OAuthError("google needs at least one scope to authorize")
        query = urlencode(
            {
                "client_id": self._client_id(),
                "redirect_uri": self.redirect_url,
                "response_type": "code",
                "scope": " ".join(scopes),
                "state": state,
                "access_type": "offline",
                "prompt": "consent",
                "include_granted_scopes": "true",
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
        auth = self._auth(org_id, payload, previous=None)
        if auth.refresh_token is None:
            raise OAuthError("google returned no refresh token; the grant is not offline")
        return auth

    async def refresh(self, auth: ProviderAuth) -> ProviderAuth:
        """New tokens for an expiring credential. A revoked grant is an OAuthError."""
        if auth.provider != self.name:
            raise OAuthError(f"a {auth.provider} credential cannot be refreshed by google")
        if auth.refresh_token is None:
            raise OAuthError("the google credential has no refresh token; reconnect google")
        payload = await self._token(
            {
                "grant_type": "refresh_token",
                "refresh_token": auth.refresh_token.get_secret_value(),
            }
        )
        return self._auth(auth.org_id, payload, previous=auth)

    def _client_id(self) -> str:
        if not self.settings.client_id:
            raise OAuthError("providers.google.client_id is not set")
        return self.settings.client_id

    def _client_secret(self) -> str:
        secret = self.settings.client_secret.get_secret_value()
        if not secret:
            raise OAuthError("providers.google.client_secret is not set")
        return secret

    async def _token(self, form: dict[str, str]) -> dict[str, Any]:
        """The parsed token response. A transport or provider failure is an OAuthError."""
        body = dict(form)
        body["client_id"] = self._client_id()
        body["client_secret"] = self._client_secret()
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECS) as client:
                response = await client.post(TOKEN_URL, data=body)
        except httpx.HTTPError as exc:
            raise OAuthError(f"google could not be reached: {type(exc).__name__}") from exc
        if response.is_error:
            raise OAuthError(f"google rejected the token request: {_reason(response)}")
        try:
            parsed = response.json()
        except ValueError as exc:
            raise OAuthError("google returned a token response that is not json") from exc
        if not isinstance(parsed, dict):
            raise OAuthError("google returned a token response that is not an object")
        return parsed

    def _auth(
        self, org_id: OrgId, payload: dict[str, Any], previous: ProviderAuth | None
    ) -> ProviderAuth:
        """A credential from a token response, keeping what the response leaves out."""
        access = payload.get("access_token")
        if not isinstance(access, str) or not access:
            raise OAuthError("google returned no access token")
        issued = payload.get("refresh_token")
        refresh = (
            SecretStr(issued)
            if isinstance(issued, str) and issued
            else (previous.refresh_token if previous else None)
        )
        scope = payload.get("scope")
        scopes = (
            tuple(scope.split())
            if isinstance(scope, str) and scope
            else (previous.scopes if previous else ())
        )
        lifetime = payload.get("expires_in")
        expires_at = (
            datetime.now(UTC) + timedelta(seconds=float(lifetime))
            if isinstance(lifetime, int | float) and not isinstance(lifetime, bool)
            else None
        )
        return ProviderAuth(
            org_id=org_id,
            provider=self.name,
            access_token=SecretStr(access),
            scopes=scopes,
            expires_at=expires_at,
            refresh_token=refresh,
        )


def _reason(response: httpx.Response) -> str:
    """The failure as a status and the OAuth error code, never the response body."""
    try:
        parsed = response.json()
    except ValueError:
        parsed = None
    code = parsed.get("error") if isinstance(parsed, dict) else None
    named = f" {code}" if isinstance(code, str) and ERROR_CODE.fullmatch(code) else ""
    return f"HTTP {response.status_code}{named}"
