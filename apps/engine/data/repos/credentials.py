"""The credentials table. Tokens are sealed by the vault before insert and opened on read."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from engine.core.types import MemberRef, OrgId, ProviderAuth
from engine.data.crypto import Vault
from engine.data.db import org_uuid, store_errors
from engine.data.tables import CredentialRow


class PgCredentials:
    """The Postgres implementation of CredentialStore."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], vault: Vault) -> None:
        self._sessions = sessions
        self._vault = vault

    def _auth(self, row: CredentialRow) -> ProviderAuth:
        """The credential one row holds, with its tokens opened."""
        return ProviderAuth(
            org_id=OrgId(str(row.org_id)),
            provider=row.provider,
            access_token=self._vault.open(row.access_token),
            scopes=tuple(row.scopes),
            expires_at=row.expires_at,
            refresh_token=None
            if row.refresh_token is None
            else self._vault.open(row.refresh_token),
        )

    async def get(self, org_id: OrgId, provider: str) -> ProviderAuth | None:
        """This org's credential for the provider, or None when it has none that is valid."""
        statement = select(CredentialRow).where(
            CredentialRow.org_id == org_uuid(org_id),
            CredentialRow.provider == provider,
            CredentialRow.valid.is_(True),
        )
        async with store_errors("credentials.get"), self._sessions() as session:
            row = (await session.scalars(statement)).one_or_none()
            return None if row is None else self._auth(row)

    async def put(self, auth: ProviderAuth, connected_by: MemberRef) -> None:
        """Seal and store the credential, replacing the one this org had for the provider."""
        refresh = None if auth.refresh_token is None else self._vault.seal(auth.refresh_token)
        changed = {
            "access_token": self._vault.seal(auth.access_token),
            "refresh_token": refresh,
            "scopes": list(auth.scopes),
            "expires_at": auth.expires_at,
            "connected_by_platform": connected_by.platform,
            "connected_by_user": connected_by.user_id,
            "valid": True,
        }
        statement = (
            insert(CredentialRow)
            .values(org_id=org_uuid(auth.org_id), provider=auth.provider, **changed)
            .on_conflict_do_update(
                index_elements=[CredentialRow.org_id, CredentialRow.provider], set_=changed
            )
        )
        async with store_errors("credentials.put"), self._sessions() as session, session.begin():
            await session.execute(statement)

    async def connected(self, org_id: OrgId) -> frozenset[str]:
        """The providers this org has a valid credential for."""
        statement = select(CredentialRow.provider).where(
            CredentialRow.org_id == org_uuid(org_id), CredentialRow.valid.is_(True)
        )
        async with store_errors("credentials.connected"), self._sessions() as session:
            return frozenset((await session.scalars(statement)).all())

    async def expiring(self, before: datetime) -> list[ProviderAuth]:
        """Every valid credential of every org that expires before then."""
        statement = (
            select(CredentialRow)
            .where(
                CredentialRow.valid.is_(True),
                CredentialRow.expires_at.is_not(None),
                CredentialRow.expires_at < before,
            )
            .order_by(CredentialRow.expires_at)
        )
        async with store_errors("credentials.expiring"), self._sessions() as session:
            rows = (await session.scalars(statement)).all()
            return [self._auth(row) for row in rows]

    async def mark_invalid(self, org_id: OrgId, provider: str) -> None:
        """Mark the credential unusable, so the org is asked to connect again."""
        statement = (
            update(CredentialRow)
            .where(CredentialRow.org_id == org_uuid(org_id), CredentialRow.provider == provider)
            .values(valid=False)
        )
        scope = "credentials.mark_invalid"
        async with store_errors(scope), self._sessions() as session, session.begin():
            await session.execute(statement)
