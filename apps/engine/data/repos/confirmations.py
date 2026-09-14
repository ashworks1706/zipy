"""The pending_confirmations table. take deletes the row it returns."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class PgConfirmations:
    """The Postgres implementation of ConfirmationStore."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions
