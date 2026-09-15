"""The zoom provider."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, ConfigDict, SecretStr

from engine.auth.providers.base import BaseProvider
from engine.core.types import Job, OAuthError, OrgId, ProviderAuth

AUTHORIZE_URL = "https://zoom.us/oauth/authorize"
TOKEN_URL = "https://zoom.us/oauth/token"

# Seconds a token request may take before it is an OAuthError.
TIMEOUT_SECS = 30.0

# Seconds a webhook timestamp may lag before the request is refused.
WEBHOOK_MAX_AGE_SECS = 300

# The OAuth error codes a failure message may repeat from the provider.
ERROR_CODE = re.compile(r"[a-z_]{1,64}")


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
        """Where the admin is sent to grant access."""
        if not scopes:
            raise OAuthError("zoom needs at least one scope to authorize")
        query = urlencode(
            {
                "client_id": self._client_id(),
                "redirect_uri": self.redirect_url,
                "response_type": "code",
                "scope": " ".join(scopes),
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
        auth = self._auth(org_id, payload, previous=None)
        if auth.refresh_token is None:
            raise OAuthError("zoom returned no refresh token")
        return auth

    async def refresh(self, auth: ProviderAuth) -> ProviderAuth:
        """New tokens for an expiring credential. A revoked grant is an OAuthError."""
        if auth.provider != self.name:
            raise OAuthError(f"a {auth.provider} credential cannot be refreshed by zoom")
        if auth.refresh_token is None:
            raise OAuthError("the zoom credential has no refresh token; reconnect zoom")
        payload = await self._token(
            {
                "grant_type": "refresh_token",
                "refresh_token": auth.refresh_token.get_secret_value(),
            }
        )
        return self._auth(auth.org_id, payload, previous=auth)

    async def webhook(self, headers: Mapping[str, str], body: bytes) -> Job | None:
        """Verifies the zoom signature over the body and returns no job."""
        self.verify_webhook(headers, body, datetime.now(UTC))
        return None

    def verify_webhook(self, headers: Mapping[str, str], body: bytes, now: datetime) -> str:
        """The verified event name. A missing, stale or wrong signature is an OAuthError."""
        secret = self.settings.webhook_secret.get_secret_value()
        if not secret:
            raise OAuthError("providers.zoom.webhook_secret is not set")
        sent = {key.lower(): value for key, value in headers.items()}
        signature = sent.get("x-zm-signature", "")
        timestamp = sent.get("x-zm-request-timestamp", "")
        if not signature or not timestamp:
            raise OAuthError("the zoom webhook has no signature")
        if not timestamp.isdigit():
            raise OAuthError("the zoom webhook timestamp is not a number")
        sent_at = datetime.fromtimestamp(int(timestamp), UTC)
        if abs(now - sent_at) > timedelta(seconds=WEBHOOK_MAX_AGE_SECS):
            raise OAuthError("the zoom webhook timestamp is outside the accepted window")
        message = b"v0:" + timestamp.encode() + b":" + body
        digest = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, f"v0={digest}"):
            raise OAuthError("the zoom webhook signature does not verify")
        return _event(body)

    def _client_id(self) -> str:
        if not self.settings.client_id:
            raise OAuthError("providers.zoom.client_id is not set")
        return self.settings.client_id

    def _client_secret(self) -> str:
        secret = self.settings.client_secret.get_secret_value()
        if not secret:
            raise OAuthError("providers.zoom.client_secret is not set")
        return secret

    async def _token(self, form: dict[str, str]) -> dict[str, Any]:
        """The parsed token response. A transport or provider failure is an OAuthError."""
        credentials = (self._client_id(), self._client_secret())
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECS) as client:
                response = await client.post(TOKEN_URL, data=form, auth=credentials)
        except httpx.HTTPError as exc:
            raise OAuthError(f"zoom could not be reached: {type(exc).__name__}") from exc
        if response.is_error:
            raise OAuthError(f"zoom rejected the token request: {_reason(response)}")
        try:
            parsed = response.json()
        except ValueError as exc:
            raise OAuthError("zoom returned a token response that is not json") from exc
        if not isinstance(parsed, dict):
            raise OAuthError("zoom returned a token response that is not an object")
        return parsed

    def _auth(
        self, org_id: OrgId, payload: dict[str, Any], previous: ProviderAuth | None
    ) -> ProviderAuth:
        """A credential from a token response, keeping what the response leaves out."""
        access = payload.get("access_token")
        if not isinstance(access, str) or not access:
            raise OAuthError("zoom returned no access token")
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


def _event(body: bytes) -> str:
    """The event name a verified webhook body carries."""
    try:
        parsed = json.loads(body)
    except (UnicodeDecodeError, ValueError) as exc:
        raise OAuthError("the zoom webhook body is not json") from exc
    event = parsed.get("event") if isinstance(parsed, dict) else None
    if not isinstance(event, str) or not event:
        raise OAuthError("the zoom webhook body names no event")
    return event


def _reason(response: httpx.Response) -> str:
    """The failure as a status and the OAuth error code, never the response body."""
    try:
        parsed = response.json()
    except ValueError:
        parsed = None
    code = parsed.get("error") if isinstance(parsed, dict) else None
    named = f" {code}" if isinstance(code, str) and ERROR_CODE.fullmatch(code) else ""
    return f"HTTP {response.status_code}{named}"
