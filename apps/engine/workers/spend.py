"""Monthly spend reset on the first of the month."""

from __future__ import annotations

from engine.core.protocols import OrgStore


async def reset_monthly_spend(orgs: OrgStore) -> None:
    """Zero every org's spend."""
    await orgs.reset_spend()
