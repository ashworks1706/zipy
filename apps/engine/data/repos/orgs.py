"""The orgs and members tables."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from engine.core.types import MemberRef, Org, OrgId, Role, StoreError
from engine.data.db import org_uuid, store_errors
from engine.data.tables import MemberRow, OrgRow


def _org(row: OrgRow) -> Org:
    """The org one row describes."""
    return Org(
        org_id=OrgId(str(row.org_id)),
        name=row.name,
        setup_complete=row.setup_complete,
        budget_cents=row.budget_cents,
        spent_cents=row.spent_cents,
    )


class PgOrgs:
    """The Postgres implementation of OrgStore."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get(self, org_id: OrgId) -> Org | None:
        """The org, or None when no row has that id."""
        async with store_errors("orgs.get"), self._sessions() as session:
            row = await session.get(OrgRow, org_uuid(org_id))
            return None if row is None else _org(row)

    async def create(self, name: str, budget_cents: int) -> Org:
        """A new org with a generated id and no spend."""
        org = Org(
            org_id=OrgId(str(uuid4())),
            name=name,
            setup_complete=False,
            budget_cents=budget_cents,
            spent_cents=0,
        )
        async with store_errors("orgs.create"), self._sessions() as session, session.begin():
            session.add(
                OrgRow(
                    org_id=org_uuid(org.org_id),
                    name=org.name,
                    setup_complete=org.setup_complete,
                    budget_cents=org.budget_cents,
                    spent_cents=org.spent_cents,
                )
            )
        return org

    async def role(self, org_id: OrgId, member: MemberRef) -> Role:
        """The member's role in this org. A member with no row is a member."""
        async with store_errors("orgs.role"), self._sessions() as session:
            stored = await session.scalar(
                select(MemberRow.role).where(
                    MemberRow.org_id == org_uuid(org_id),
                    MemberRow.platform == member.platform,
                    MemberRow.user_id == member.user_id,
                )
            )
        if stored is None:
            return Role.MEMBER
        try:
            return Role(stored)
        except ValueError as exc:
            raise StoreError(f"members.role holds {stored}, which is not a role") from exc

    async def set_role(self, org_id: OrgId, member: MemberRef, role: Role) -> None:
        """Give the member this role in this org, replacing any it had."""
        statement = (
            insert(MemberRow)
            .values(
                org_id=org_uuid(org_id),
                platform=member.platform,
                user_id=member.user_id,
                role=role.value,
            )
            .on_conflict_do_update(
                index_elements=[MemberRow.org_id, MemberRow.platform, MemberRow.user_id],
                set_={"role": role.value},
            )
        )
        async with store_errors("orgs.set_role"), self._sessions() as session, session.begin():
            await session.execute(statement)

    async def add_spend(self, org_id: OrgId, cents: float) -> None:
        """Add the cost of one model call to the org's spend."""
        statement = (
            update(OrgRow)
            .where(OrgRow.org_id == org_uuid(org_id))
            .values(spent_cents=OrgRow.spent_cents + cents)
        )
        async with store_errors("orgs.add_spend"), self._sessions() as session, session.begin():
            await session.execute(statement)

    async def reset_spend(self) -> None:
        """Zero every org's spend."""
        async with store_errors("orgs.reset_spend"), self._sessions() as session, session.begin():
            await session.execute(update(OrgRow).values(spent_cents=0))
