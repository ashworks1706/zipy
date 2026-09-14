"""structlog setup: readable lines in dev, JSON lines in prod, org and member bound per request."""

from __future__ import annotations

import structlog

from engine.core.config import App
from engine.core.types import RequestContext


def configure(app: App) -> None:
    """Install the process-wide structlog configuration."""
    raise NotImplementedError


def bind(ctx: RequestContext) -> structlog.stdlib.BoundLogger:
    """A logger with org_id, platform, member and request_id on every line."""
    raise NotImplementedError


def get(name: str) -> structlog.stdlib.BoundLogger:
    """A named logger with no request bound."""
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
