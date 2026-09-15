"""structlog setup: readable lines in dev, JSON lines in prod, org and member bound per request."""

from __future__ import annotations

import logging
import sys

import structlog

from engine.core.config import App
from engine.core.types import RequestContext


def configure(app: App) -> None:
    """Install the process-wide structlog configuration."""
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=logging.INFO, force=True)
    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer()
        if app.env == "prod"
        else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def bind(ctx: RequestContext) -> structlog.stdlib.BoundLogger:
    """A logger with org_id, platform, member and request_id on every line."""
    logger: structlog.stdlib.BoundLogger = get("engine.request").bind(
        org_id=str(ctx.org_id),
        platform=ctx.channel.platform,
        workspace_id=ctx.channel.workspace.workspace_id,
        channel_id=ctx.channel.channel_id,
        member=ctx.member.user_id,
        role=ctx.role.value,
        request_id=ctx.request_id,
    )
    return logger


def get(name: str) -> structlog.stdlib.BoundLogger:
    """A named logger with no request bound."""
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
