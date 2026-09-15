"""Refreshes credentials that expire within the window; a revoked one is marked invalid."""

from __future__ import annotations

from datetime import timedelta

from engine.auth.providers.registry import Providers
from engine.core.config import Workers
from engine.core.protocols import CredentialStore, Notifier
from engine.core.types import ConfigError, MemberRef, OAuthError, ProviderAuth
from engine.telemetry.logging import get
from engine.workers.scheduler import now_utc

log = get("engine.workers.token_refresh")

# The connector of record for a credential the worker refreshed rather than a person.
REFRESHER = MemberRef(platform="system", user_id="token_refresh")


async def refresh_expiring(
    workers: Workers, credentials: CredentialStore, providers: Providers, notifier: Notifier
) -> None:
    """Refresh every credential expiring within the window; notify the org of a revoked one."""
    window = now_utc() + timedelta(minutes=workers.token_refresh_window_minutes)
    for auth in await credentials.expiring(window):
        await _refresh(auth, credentials, providers, notifier)


async def _refresh(
    auth: ProviderAuth,
    credentials: CredentialStore,
    providers: Providers,
    notifier: Notifier,
) -> None:
    """One credential. A revoked grant is marked invalid and the org is told to reconnect."""
    try:
        provider = providers.get(auth.provider)
    except ConfigError as exc:
        log.warning("credential has no enabled provider", provider=auth.provider, reason=str(exc))
        return
    try:
        refreshed = await provider.refresh(auth)
    except OAuthError as exc:
        await credentials.mark_invalid(auth.org_id, auth.provider)
        await notifier.notify(
            auth.org_id,
            f"Zipy lost access to {auth.provider}: {exc}. An admin can reconnect it with "
            f"connect {auth.provider}.",
        )
        log.warning("credential revoked", provider=auth.provider, org_id=str(auth.org_id))
        return
    await credentials.put(refreshed, REFRESHER)
    log.info("credential refreshed", provider=auth.provider, org_id=str(auth.org_id))
