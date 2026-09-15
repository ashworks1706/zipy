"""The workspaces table: which org each platform workspace belongs to."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from engine.core.types import ChannelRef, OrgId, Workspace, WorkspaceRef
from engine.data.crypto import Vault
from engine.data.db import org_uuid, store_errors
from engine.data.tables import WorkspaceRow


def _workspace(row: WorkspaceRow) -> Workspace:
    """The workspace one row describes."""
    ref = WorkspaceRef(platform=row.platform, workspace_id=row.workspace_id)
    notice = ChannelRef(ref, row.notice_channel_id) if row.notice_channel_id else None
    return Workspace(ref=ref, org_id=OrgId(str(row.org_id)), name=row.name, notice_channel=notice)


class PgWorkspaces:
    """The Postgres implementation of WorkspaceStore. Bot tokens are sealed by the vault."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], vault: Vault) -> None:
        self._sessions = sessions
        self._vault = vault

    async def get(self, ref: WorkspaceRef) -> Workspace | None:
        """The workspace link, or None when the workspace belongs to no org."""
        async with store_errors("workspaces.get"), self._sessions() as session:
            row = await session.get(WorkspaceRow, (ref.platform, ref.workspace_id))
            return None if row is None else _workspace(row)

    async def link(self, workspace: Workspace) -> None:
        """Link the workspace to its org, replacing any link it had."""
        notice = workspace.notice_channel.channel_id if workspace.notice_channel else ""
        changed = {
            "org_id": org_uuid(workspace.org_id),
            "name": workspace.name,
            "notice_channel_id": notice,
        }
        statement = (
            insert(WorkspaceRow)
            .values(
                platform=workspace.ref.platform,
                workspace_id=workspace.ref.workspace_id,
                installed_by="",
                bot_token=None,
                **changed,
            )
            .on_conflict_do_update(
                index_elements=[WorkspaceRow.platform, WorkspaceRow.workspace_id], set_=changed
            )
        )
        async with store_errors("workspaces.link"), self._sessions() as session, session.begin():
            await session.execute(statement)

    async def unlink(self, ref: WorkspaceRef) -> None:
        """Drop the link, leaving the org and its other workspaces alone."""
        statement = delete(WorkspaceRow).where(
            WorkspaceRow.platform == ref.platform, WorkspaceRow.workspace_id == ref.workspace_id
        )
        async with store_errors("workspaces.unlink"), self._sessions() as session, session.begin():
            await session.execute(statement)

    async def of_org(self, org_id: OrgId) -> list[Workspace]:
        """Every workspace linked to this org."""
        statement = (
            select(WorkspaceRow)
            .where(WorkspaceRow.org_id == org_uuid(org_id))
            .order_by(WorkspaceRow.platform, WorkspaceRow.workspace_id)
        )
        async with store_errors("workspaces.of_org"), self._sessions() as session:
            rows = (await session.scalars(statement)).all()
            return [_workspace(row) for row in rows]
