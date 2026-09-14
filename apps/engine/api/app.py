"""The FastAPI application."""

from __future__ import annotations

from collections.abc import Mapping

from fastapi import APIRouter, FastAPI

from engine.api.routes import health, metrics, oauth, webhooks
from engine.api.routes.oauth import OAuthRoutes
from engine.api.routes.webhooks import WebhookRoutes
from engine.telemetry.metrics import Metrics


def create_app(
    oauth_routes: OAuthRoutes,
    webhook_routes: WebhookRoutes,
    platform_routers: Mapping[str, APIRouter],
    registry: Metrics | None,
) -> FastAPI:
    """The app with every router mounted; each platform's under /platforms/name."""
    app = FastAPI(title="zipy", docs_url=None, redoc_url=None)
    app.include_router(health.router)
    if registry is not None:
        app.include_router(metrics.router(registry))
    app.include_router(oauth.router(oauth_routes))
    app.include_router(webhooks.router(webhook_routes))
    for name, platform_router in platform_routers.items():
        app.include_router(platform_router, prefix=f"/platforms/{name}")
    return app
