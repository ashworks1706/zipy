"""The pending_confirmations table. take deletes the row it returns."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from engine.core.types import (
    ChannelRef,
    ChatMessage,
    MemberRef,
    OrgId,
    PendingConfirmation,
    Speaker,
    StoreError,
    SubAgent,
    ToolCall,
    WorkspaceRef,
)
from engine.data.db import org_uuid, store_errors
from engine.data.tables import PendingConfirmationRow


def _parameters(call: ToolCall) -> dict[str, object]:
    """The parameters column of a held call: the model's call id and its arguments."""
    return {"call_id": call.id, "arguments": dict(call.arguments)}


def _message_row(message: ChatMessage) -> dict[str, Any]:
    """One message of a suspended sub-agent, as it is stored. Images are not kept: their links
    expire, and a sub-agent is given none."""
    return {
        "speaker": message.speaker.value,
        "content": message.content,
        "name": message.name,
        "tool_call_id": message.tool_call_id,
        "tool_calls": [
            {"id": call.id, "name": call.name, "arguments": dict(call.arguments)}
            for call in message.tool_calls
        ],
    }


def _message(stored: dict[str, Any]) -> ChatMessage:
    """One stored message, read back."""
    return ChatMessage(
        speaker=Speaker(str(stored.get("speaker", Speaker.USER.value))),
        content=str(stored.get("content", "")),
        name=str(stored.get("name", "")),
        tool_call_id=str(stored.get("tool_call_id", "")),
        tool_calls=tuple(
            ToolCall(
                id=str(one.get("id", "")),
                name=str(one.get("name", "")),
                arguments=dict(one.get("arguments") or {}),
            )
            for one in stored.get("tool_calls") or []
            if isinstance(one, dict)
        ),
    )


def _sub_agent_row(sub: SubAgent) -> dict[str, Any]:
    """The sub_agent column of a held call."""
    return {
        "call_id": sub.call_id,
        "task": sub.task,
        "tools": list(sub.tools),
        "turns_used": sub.turns_used,
        "messages": [_message_row(message) for message in sub.messages],
    }


def _sub_agent(stored: Any) -> SubAgent | None:
    """The sub-agent one row held, or None when the request itself asked."""
    if not isinstance(stored, dict):
        return None
    call_id = stored.get("call_id")
    if not isinstance(call_id, str) or not call_id:
        return None
    return SubAgent(
        call_id=call_id,
        task=str(stored.get("task", "")),
        tools=tuple(str(name) for name in stored.get("tools") or []),
        messages=tuple(
            _message(one) for one in stored.get("messages") or [] if isinstance(one, dict)
        ),
        turns_used=int(stored.get("turns_used", 0) or 0),
    )


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
        sub_agent=_sub_agent(row.sub_agent),
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
                    sub_agent=_sub_agent_row(pending.sub_agent) if pending.sub_agent else None,
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
