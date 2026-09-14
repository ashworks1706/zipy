"""The credentials table. Tokens are sealed by the vault before insert and opened on read."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from engine.data.crypto import Vault


class PgCredentials:
    """The Postgres implementation of CredentialStore."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], vault: Vault) -> None:
        self._sessions = sessions
        self._vault = vault
