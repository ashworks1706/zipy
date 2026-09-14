"""POST /webhooks/{provider}: the provider verifies the request and names a job to queue."""

from __future__ import annotations

from fastapi import APIRouter, Request

from engine.auth.providers.registry import Providers
from engine.core.protocols import JobQueue


class WebhookRoutes:
    """Handlers for every provider's webhooks."""

    def __init__(self, providers: Providers, queue: JobQueue) -> None:
        self._providers = providers
        self._queue = queue

    async def receive(self, provider: str, request: Request) -> dict[str, str]:
        """Pass headers and body to the provider; queue the job it returns."""
        raise NotImplementedError


def router(routes: WebhookRoutes) -> APIRouter:
    """The webhook routes."""
    api = APIRouter(prefix="/webhooks")
    api.add_api_route("/{provider}", routes.receive, methods=["POST"])
    return api
