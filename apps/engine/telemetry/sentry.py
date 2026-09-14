"""Sentry error reporting. An empty DSN installs nothing."""

from __future__ import annotations

from engine.core.config import Telemetry


def configure(telemetry: Telemetry, env: str, release: str) -> None:
    """Initialise the Sentry SDK when a DSN is set."""
    raise NotImplementedError
