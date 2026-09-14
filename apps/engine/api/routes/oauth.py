"""GET /auth/{provider} redirects to the provider; its callback stores the tokens."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse

from engine.auth.providers.registry import Providers
from engine.core.protocols import CredentialStore, Notifier


class OAuthRoutes:
    """Handlers for the connect flow of every enabled provider."""

    def __init__(
        self, providers: Providers, credentials: CredentialStore, notifier: Notifier
    ) -> None:
        self._providers = providers
        self._credentials = credentials
        self._notifier = notifier

    async def start(self, provider: str, state: str) -> RedirectResponse:
        """Verify the signed state from the private link and redirect to the provider."""
        raise NotImplementedError

    async def callback(self, provider: str, code: str, state: str) -> HTMLResponse:
        """Exchange the code, store the sealed tokens for the state's org, and notify the org."""
        raise NotImplementedError


def router(routes: OAuthRoutes) -> APIRouter:
    """The OAuth routes."""
    api = APIRouter(prefix="/auth")
    api.add_api_route("/{provider}", routes.start, methods=["GET"])
    api.add_api_route("/{provider}/callback", routes.callback, methods=["GET"])
    return api
