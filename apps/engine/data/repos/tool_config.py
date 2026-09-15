"""The org_tool_config table."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from engine.core.types import OrgId, OrgToolConfig
from engine.data.db import org_uuid, store_errors
from engine.data.tables import OrgToolConfigRow


class PgToolConfig:
    """The Postgres implementation of ToolConfigStore."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def overrides(self, org_id: OrgId) -> dict[str, OrgToolConfig]:
        """This org's overrides, by tool name."""
        statement = select(OrgToolConfigRow).where(OrgToolConfigRow.org_id == org_uuid(org_id))
        async with store_errors("org_tool_config.overrides"), self._sessions() as session:
            rows = (await session.scalars(statement)).all()
            return {
                row.tool_name: OrgToolConfig(
                    tool=row.tool_name,
                    enabled=row.enabled,
                    overrides=dict(row.config_overrides),
                )
                for row in rows
            }

    async def set(self, org_id: OrgId, config: OrgToolConfig) -> None:
        """Store this org's override of one tool, replacing the one it had."""
        changed = {"enabled": config.enabled, "config_overrides": dict(config.overrides)}
        statement = (
            insert(OrgToolConfigRow)
            .values(org_id=org_uuid(org_id), tool_name=config.tool, **changed)
            .on_conflict_do_update(
                index_elements=[OrgToolConfigRow.org_id, OrgToolConfigRow.tool_name], set_=changed
            )
        )
        scope = "org_tool_config.set"
        async with store_errors(scope), self._sessions() as session, session.begin():
            await session.execute(statement)
