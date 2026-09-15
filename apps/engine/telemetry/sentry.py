"""Sentry error reporting. An empty DSN installs nothing."""

from __future__ import annotations

import sentry_sdk

from engine.core.config import Telemetry


def configure(telemetry: Telemetry, env: str, release: str) -> None:
    """Initialise the Sentry SDK when a DSN is set."""
    dsn = telemetry.sentry_dsn.get_secret_value()
    if not dsn:
        return
    sentry_sdk.init(
        dsn=dsn,
        environment=env,
        release=release,
        traces_sample_rate=telemetry.sentry_traces_sample_rate,
        send_default_pii=False,
        max_request_body_size="never",
    )
