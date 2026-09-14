"""GET /metrics for Prometheus."""

from __future__ import annotations

from fastapi import APIRouter, Response

from engine.telemetry.metrics import Metrics


def router(metrics: Metrics) -> APIRouter:
    """The metrics route over one registry."""
    api = APIRouter()

    async def scrape() -> Response:
        body, content_type = metrics.exposition()
        return Response(body, media_type=content_type)

    api.add_api_route("/metrics", scrape, methods=["GET"], include_in_schema=False)
    return api
