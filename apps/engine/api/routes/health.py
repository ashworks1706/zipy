"""Liveness for Uptime Kuma and the container healthcheck."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    """ok while the process serves requests."""
    return {"status": "ok"}
