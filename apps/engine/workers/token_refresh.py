"""Refreshes credentials that expire within the window; a revoked one is marked invalid."""

from __future__ import annotations

from engine.auth.providers.registry import Providers
from engine.core.config import Workers
from engine.core.protocols import CredentialStore, Notifier


async def refresh_expiring(
    workers: Workers, credentials: CredentialStore, providers: Providers, notifier: Notifier
) -> None:
    """Refresh every credential expiring within the window; notify the org of a revoked one."""
    raise NotImplementedError
