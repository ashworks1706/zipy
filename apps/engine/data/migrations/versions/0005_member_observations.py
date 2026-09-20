"""member_observations, the evidence behind member_state

Revision ID: 0005_member_observations
Revises: 0004_sub_agent
Create Date: 2026-09-20

member_state holds a moving average, which is the endpoint of a trajectory and not the
trajectory. Once a signal is applied the dimension it moved, the target it moved toward and the
category of evidence behind it are gone, and no later query can recover them. Every question
about how the state got where it is needs the sequence, so the sequence is kept.

It carries no text column, for the same reason member_state has none. arm and model are here from
the start because a variant recorded after the fact is a guess: arm names what a request ran
under, and model names what served it, so a provider changing a model underneath a deployment is
visible rather than read as the state drifting on its own.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_member_observations"
down_revision = "0004_sub_agent"
branch_labels = None
depends_on = None

#: The identity of a member, the same trio the members table is keyed by.
ID = sa.String(64)


def upgrade() -> None:
    op.create_table(
        "member_observations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("platform", ID, nullable=False),
        sa.Column("user_id", ID, nullable=False),
        sa.Column("dimension", ID, nullable=False),
        sa.Column("target", sa.Double(), nullable=False),
        sa.Column("evidence", ID, nullable=False),
        sa.Column("weight", sa.Double(), nullable=False),
        sa.Column("request_id", ID, nullable=False, server_default=""),
        sa.Column("arm", ID, nullable=False, server_default=""),
        sa.Column("model", sa.String(200), nullable=False, server_default=""),
        sa.Column(
            "at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.org_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_member_observations_org_id"), "member_observations", ["org_id"], unique=False
    )
    op.create_index(
        "ix_member_observations_member",
        "member_observations",
        ["org_id", "platform", "user_id", "at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_member_observations_member", table_name="member_observations")
    op.drop_index(op.f("ix_member_observations_org_id"), table_name="member_observations")
    op.drop_table("member_observations")
