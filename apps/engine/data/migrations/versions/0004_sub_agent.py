"""a held call remembers the sub-agent that asked

Revision ID: 0004_sub_agent
Revises: 0003_member_state
Create Date: 2026-09-18

A destructive call inside a sub-agent stops two levels. What the parent was doing is rebuilt from
the platform's history and the result the sub-agent goes on to produce, the way a resumed request
already is. The sub-agent's own messages are the part nothing else holds, so they wait here with
its task, its tools and the turns it had taken.

Nullable, because the request itself asking is still the ordinary case. The row is deleted when
the answer comes and swept when it expires, so this holds a conversation for as long as a
confirmation waits and no longer.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_sub_agent"
down_revision = "0003_member_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pending_confirmations",
        sa.Column("sub_agent", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pending_confirmations", "sub_agent")
