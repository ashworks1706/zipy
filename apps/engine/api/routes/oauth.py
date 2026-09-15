"""GET /auth/{provider} redirects to the provider; its callback stores the tokens."""

from __future__ import annotations

import html
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import SecretStr

from engine.auth.providers.registry import Providers
from engine.auth.state import ConnectState, verify
from engine.core.protocols import CredentialStore, Notifier
from engine.core.types import ConfigError, OAuthError, ZipyError
from engine.telemetry.logging import get

# Seconds a connect link stays usable after the gateway sends it.
DEFAULT_STATE_MAX_AGE_SECS = 900

# Sent with every response so the page carries nothing and the code reaches no other origin.
HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
    "Referrer-Policy": "no-referrer",
}

# What a caller sees when a link does not verify. The reason goes to the log, not the page.
INVALID = "This connect link is invalid or has expired. Ask Zipy for a new one."

# What a scrubbed authorization code or state token reads as in a log line.
REDACTED = "[redacted]"

log = get(__name__)


class OAuthRoutes:
    """Handlers for the connect flow of every enabled provider."""

    def __init__(
        self,
        providers: Providers,
        credentials: CredentialStore,
        notifier: Notifier,
        state_key: SecretStr,
        scopes: Mapping[str, Sequence[str]],
        state_max_age_secs: int = DEFAULT_STATE_MAX_AGE_SECS,
    ) -> None:
        self._providers = providers
        self._credentials = credentials
        self._notifier = notifier
        self._state_key = state_key
        self._scopes = scopes
        self._state_max_age_secs = state_max_age_secs

    async def start(self, provider: str, state: str) -> RedirectResponse:
        """Verify the signed state from the private link and redirect to the provider."""
        try:
            connect = self._connect(provider, state)
            plugin = self._providers.get(provider)
            target = plugin.authorize_url(state, list(self._scopes.get(provider, ())))
        except ZipyError as exc:
            log.warning("oauth_start_refused", provider=provider, reason=_scrub(exc, state))
            raise HTTPException(status_code=400, detail=INVALID) from exc
        log.info("oauth_start", provider=provider, org_id=connect.org_id)
        return RedirectResponse(target, status_code=307, headers=HEADERS)

    async def callback(
        self, provider: str, state: str, code: str = "", error: str = ""
    ) -> HTMLResponse:
        """Exchange the code, store the sealed tokens for the state's org, and notify the org."""
        try:
            connect = self._connect(provider, state)
        except ZipyError as exc:
            log.warning("oauth_callback_refused", provider=provider, reason=_scrub(exc, state))
            return _page(INVALID, status_code=400)
        if error or not code:
            log.warning(
                "oauth_callback_denied", provider=provider, org_id=connect.org_id, reason=error
            )
            return _page(f"{html.escape(provider)} was not connected.", status_code=400)
        try:
            auth = await self._providers.get(provider).exchange(connect.org_id, code)
            if auth.org_id != connect.org_id or auth.provider != provider:
                raise OAuthError(f"{provider} returned a credential for another org or provider")
            await self._credentials.put(auth, connect.member)
        except ZipyError as exc:
            log.warning(
                "oauth_callback_failed",
                provider=provider,
                org_id=connect.org_id,
                reason=_scrub(exc, state, code),
            )
            return _page(f"{html.escape(provider)} could not be connected.", status_code=400)
        log.info("oauth_connected", provider=provider, org_id=connect.org_id)
        await self._notifier.notify(connect.org_id, f"{provider} connected.")
        return _page(f"{html.escape(provider)} is connected. You can close this tab.")

    def _connect(self, provider: str, state: str) -> ConnectState:
        """The state a link carries, refused unless it was signed for this provider."""
        if provider not in self._providers.classes:
            raise ConfigError(f"provider {provider} is not a plugin")
        connect = verify(state, self._state_key, datetime.now(UTC), self._state_max_age_secs)
        if connect.provider != provider:
            raise OAuthError(f"oauth state was signed for {connect.provider}, not {provider}")
        return connect


def _scrub(exc: ZipyError, *secrets: str) -> str:
    """The error text with every authorization code and state token taken out."""
    reason = str(exc)
    for secret in secrets:
        if secret:
            reason = reason.replace(secret, REDACTED)
    return reason


def _page(message: str, status_code: int = 200) -> HTMLResponse:
    """A page with the message and nothing else."""
    body = (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        "<title>Zipy</title></head><body><main><p>"
        f"{message}</p></main></body></html>"
    )
    return HTMLResponse(body, status_code=status_code, headers=HEADERS)


def router(routes: OAuthRoutes) -> APIRouter:
    """The OAuth routes."""
    api = APIRouter(prefix="/auth")
    api.add_api_route("/{provider}", routes.start, methods=["GET"])
    api.add_api_route("/{provider}/callback", routes.callback, methods=["GET"])
    return api
