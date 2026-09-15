"""The org_context table."""

from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from engine.core.types import FactCategory, OrgFact, OrgId, StoreError
from engine.data.db import org_uuid, store_errors
from engine.data.tables import OrgContextRow


def _fact(row: OrgContextRow) -> OrgFact:
    """The fact one row holds."""
    try:
        category = FactCategory(row.category)
    except ValueError as exc:
        raise StoreError(
            f"org_context.category holds {row.category}, which is not a category"
        ) from exc
    return OrgFact(category=category, key=row.key, value=row.value)


class PgOrgContext:
    """The Postgres implementation of OrgContextStore."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def facts(self, org_id: OrgId) -> list[OrgFact]:
        """Every fact this org has told Zipy, ordered by category then key."""
        statement = (
            select(OrgContextRow)
            .where(OrgContextRow.org_id == org_uuid(org_id))
            .order_by(OrgContextRow.category, OrgContextRow.key)
        )
        async with store_errors("org_context.facts"), self._sessions() as session:
            rows = (await session.scalars(statement)).all()
            return [_fact(row) for row in rows]

    async def remember(self, org_id: OrgId, fact: OrgFact) -> None:
        """Store the fact, replacing any fact this org holds under the same key."""
        changed = {
            "category": fact.category.value,
            "value": fact.value,
            "updated_at": func.now(),
        }
        statement = (
            insert(OrgContextRow)
            .values(org_id=org_uuid(org_id), key=fact.key, **changed)
            .on_conflict_do_update(
                index_elements=[OrgContextRow.org_id, OrgContextRow.key], set_=changed
            )
        )
        scope = "org_context.remember"
        async with store_errors(scope), self._sessions() as session, session.begin():
            await session.execute(statement)

    async def forget(self, org_id: OrgId, key: str) -> None:
        """Drop this org's fact under that key."""
        statement = delete(OrgContextRow).where(
            OrgContextRow.org_id == org_uuid(org_id), OrgContextRow.key == key
        )
        async with store_errors("org_context.forget"), self._sessions() as session, session.begin():
            await session.execute(statement)
