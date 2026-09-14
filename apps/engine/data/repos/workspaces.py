"""The workspaces table: which org each platform workspace belongs to."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from engine.data.crypto import Vault


class PgWorkspaces:
    """The Postgres implementation of WorkspaceStore. Bot tokens are sealed by the vault."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], vault: Vault) -> None:
        self._sessions = sessions
        self._vault = vault
