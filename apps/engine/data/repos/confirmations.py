"""The pending_confirmations table. take deletes the row it returns."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from engine.core.types import (
    ChannelRef,
    MemberRef,
    OrgId,
    PendingConfirmation,
    StoreError,
    ToolCall,
    WorkspaceRef,
)
from engine.data.db import org_uuid, store_errors
from engine.data.tables import PendingConfirmationRow


def _parameters(call: ToolCall) -> dict[str, object]:
    """The parameters column of a held call: the model's call id and its arguments."""
    return {"call_id": call.id, "arguments": dict(call.arguments)}


def _pending(row: PendingConfirmationRow) -> PendingConfirmation:
    """The held call one row describes."""
    stored = row.parameters
    call_id = stored.get("call_id")
    arguments = stored.get("arguments")
    if not isinstance(call_id, str) or not isinstance(arguments, dict):
        raise StoreError(f"pending_confirmations.parameters of {row.id} is not a held call")
    workspace = WorkspaceRef(platform=row.platform, workspace_id=row.workspace_id)
    return PendingConfirmation(
        id=row.id,
        org_id=OrgId(str(row.org_id)),
        requested_by=MemberRef(platform=row.platform, user_id=row.requested_by),
        channel=ChannelRef(workspace, row.channel_id, row.thread_id),
        call=ToolCall(id=call_id, name=row.action, arguments=dict(arguments)),
        summary=row.summary,
        expires_at=row.expires_at,
    )


class PgConfirmations:
    """The Postgres implementation of ConfirmationStore."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def put(self, pending: PendingConfirmation) -> None:
        """Hold a destructive call until it is answered or expires."""
        async with store_errors("confirmations.put"), self._sessions() as session, session.begin():
            session.add(
                PendingConfirmationRow(
                    id=pending.id,
                    org_id=org_uuid(pending.org_id),
                    platform=pending.channel.platform,
                    workspace_id=pending.channel.workspace.workspace_id,
                    channel_id=pending.channel.channel_id,
                    thread_id=pending.channel.thread_id,
                    requested_by=pending.requested_by.user_id,
                    action=pending.call.name,
                    parameters=_parameters(pending.call),
                    summary=pending.summary,
                    expires_at=pending.expires_at,
                )
            )

    async def take(self, confirmation_id: str, now: datetime) -> PendingConfirmation | None:
        """Consume the held call, returning it only while it has not expired."""
        async with store_errors("confirmations.take"), self._sessions() as session, session.begin():
            row = await session.get(PendingConfirmationRow, confirmation_id, with_for_update=True)
            if row is None:
                return None
            pending = _pending(row)
            await session.delete(row)
        return pending if pending.expires_at > now else None

    async def purge_expired(self, now: datetime) -> int:
        """Drop every held call that has expired, and say how many."""
        statement = (
            delete(PendingConfirmationRow)
            .where(PendingConfirmationRow.expires_at <= now)
            .returning(PendingConfirmationRow.id)
        )
        scope = "confirmations.purge_expired"
        async with store_errors(scope), self._sessions() as session, session.begin():
            dropped = (await session.scalars(statement)).all()
        return len(dropped)
