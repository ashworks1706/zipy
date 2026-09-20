"""The member_state table."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from engine.core.types import (
    CollaborationState,
    Dimension,
    MemberRef,
    OrgId,
    Provenance,
    Signal,
)
from engine.core.types.collaboration import apply_signals
from engine.data.db import org_uuid, store_errors
from engine.data.tables import MemberObservationRow, MemberStateRow


def _state(row: MemberStateRow | None, member: MemberRef) -> CollaborationState:
    """What one row holds, or a state nothing has been observed into yet."""
    if row is None:
        return CollaborationState(member=member)
    scores = {
        dimension: float(row.scores[dimension.value])
        for dimension in Dimension
        if dimension.value in row.scores
    }
    return CollaborationState(
        member=member,
        scores=scores,
        observations=row.observations,
        updated_at=row.updated_at,
    )


class PgCollaboration:
    """The Postgres implementation of CollaborationStore."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def state(self, org_id: OrgId, member: MemberRef) -> CollaborationState:
        """This person's scores. A member nothing has been observed about scores neutral."""
        statement = select(MemberStateRow).where(
            MemberStateRow.org_id == org_uuid(org_id),
            MemberStateRow.platform == member.platform,
            MemberStateRow.user_id == member.user_id,
        )
        async with store_errors("member_state.state"), self._sessions() as session:
            return _state((await session.scalars(statement)).one_or_none(), member)

    async def observe(
        self,
        org_id: OrgId,
        member: MemberRef,
        signals: Sequence[Signal],
        provenance: Provenance,
    ) -> None:
        """Move this person's scores by signals, and keep the signals that moved them.

        One transaction, so a state that moved always has the observations that moved it.
        """
        if not signals:
            return
        scope = "member_state.observe"
        async with store_errors(scope), self._sessions() as session, session.begin():
            statement = select(MemberStateRow).where(
                MemberStateRow.org_id == org_uuid(org_id),
                MemberStateRow.platform == member.platform,
                MemberStateRow.user_id == member.user_id,
            )
            current = _state((await session.scalars(statement)).one_or_none(), member)
            moved = apply_signals(current, signals)
            changed = {
                "scores": {d.value: score for d, score in moved.scores.items()},
                "observations": moved.observations,
                "updated_at": moved.updated_at,
            }
            await session.execute(
                insert(MemberStateRow)
                .values(
                    org_id=org_uuid(org_id),
                    platform=member.platform,
                    user_id=member.user_id,
                    **changed,
                )
                .on_conflict_do_update(
                    index_elements=[
                        MemberStateRow.org_id,
                        MemberStateRow.platform,
                        MemberStateRow.user_id,
                    ],
                    set_=changed,
                )
            )
            await session.execute(
                insert(MemberObservationRow),
                [
                    {
                        "org_id": org_uuid(org_id),
                        "platform": member.platform,
                        "user_id": member.user_id,
                        "dimension": signal.dimension.value,
                        "target": signal.target,
                        "evidence": signal.evidence.value,
                        "weight": signal.weight,
                        "request_id": provenance.request_id,
                        "arm": provenance.arm,
                        "model": provenance.model,
                    }
                    for signal in signals
                ],
            )

    async def forget(self, org_id: OrgId, member: MemberRef) -> None:
        """Drop everything read about this person. One statement, because nothing else was kept."""
        statement = delete(MemberStateRow).where(
            MemberStateRow.org_id == org_uuid(org_id),
            MemberStateRow.platform == member.platform,
            MemberStateRow.user_id == member.user_id,
        )
        scope = "member_state.forget"
        async with store_errors(scope), self._sessions() as session, session.begin():
            await session.execute(statement)
