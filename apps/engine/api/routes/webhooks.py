"""POST /webhooks/{provider}: the provider verifies the request and names a job to queue."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from engine.auth.providers.registry import Providers
from engine.core.protocols import JobQueue
from engine.core.types import ConfigError, OAuthError
from engine.telemetry.logging import get

log = get("engine.api.webhooks")


class WebhookRoutes:
    """Handlers for every provider's webhooks."""

    def __init__(self, providers: Providers, queue: JobQueue) -> None:
        self._providers = providers
        self._queue = queue

    async def receive(self, provider: str, request: Request) -> dict[str, str]:
        """Pass headers and body to the provider; queue the job it returns."""
        try:
            plugin = self._providers.get(provider)
        except ConfigError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        body = await request.body()
        try:
            job = await plugin.webhook(dict(request.headers), body)
        except OAuthError as exc:
            log.warning("webhook rejected", provider=provider, reason=str(exc))
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        if job is None:
            return {"status": "ignored", "provider": provider}
        await self._queue.enqueue(job)
        log.info("webhook queued", provider=provider, kind=job.kind, org_id=str(job.org_id))
        return {"status": "queued", "kind": job.kind}


def router(routes: WebhookRoutes) -> APIRouter:
    """The webhook routes."""
    api = APIRouter(prefix="/webhooks")
    api.add_api_route("/{provider}", routes.receive, methods=["POST"])
    return api
