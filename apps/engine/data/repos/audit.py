"""The audit_log table. Insert only."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from engine.core.types import AuditEntry
from engine.data.db import org_uuid, store_errors
from engine.data.tables import AuditRow


class PgAudit:
    """The Postgres implementation of AuditLog."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def append(self, entry: AuditEntry) -> None:
        """Record one tool execution. Rows here are never updated or deleted."""
        async with store_errors("audit_log.append"), self._sessions() as session, session.begin():
            session.add(
                AuditRow(
                    org_id=org_uuid(entry.org_id),
                    actor_platform=entry.actor.platform,
                    actor_user=entry.actor.user_id,
                    action=entry.action,
                    target=entry.target,
                    payload=dict(entry.payload),
                    ok=entry.ok,
                    error=entry.error,
                    at=entry.at,
                )
            )
