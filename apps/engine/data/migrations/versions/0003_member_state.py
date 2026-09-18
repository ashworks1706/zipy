"""member_state, and the dead display_name column goes

Revision ID: 0003_member_state
Revises: 0002_embedding_1024
Create Date: 2026-09-18

member_state holds how one person works with the agent, as scores and a count of what they were
read from. It is a table of its own rather than columns on members, because members is
authorization data read on the path of every request and this is behavioural data written by the
runtime, with a different lifecycle and a different tolerance for being wrong.

scores is JSONB so a new dimension needs no migration, and there is no text column: the state is
what behaviour showed, never what was said.

members.display_name goes with it. Nothing has ever written it, PgOrgs.set_role sets only role,
and the name in a prompt comes from the request. A column nothing fills is a column that will
one day be read as though it were filled.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_member_state"
down_revision = "0002_embedding_1024"
branch_labels = None
depends_on = None

#: The identity of a member, the same trio the members table is keyed by.
ID = sa.String(64)


def upgrade() -> None:
    op.create_table(
        "member_state",
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("platform", ID, nullable=False),
        sa.Column("user_id", ID, nullable=False),
        sa.Column("scores", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("observations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.org_id"]),
        sa.PrimaryKeyConstraint("org_id", "platform", "user_id"),
    )
    op.drop_column("members", "display_name")


def downgrade() -> None:
    op.add_column(
        "members",
        sa.Column("display_name", sa.String(200), nullable=False, server_default=""),
    )
    op.drop_table("member_state")
