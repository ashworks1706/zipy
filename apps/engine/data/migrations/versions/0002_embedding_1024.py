"""embedding vectors of 1024 dimensions

Revision ID: 0002_embedding_1024
Revises: 0001_initial
Create Date: 2026-09-15

The default embedding model is the local llama-server one, which returns 1024 dimensions.
pgvector fixes the width in the column type, so the stored vectors go and the sources are
re-synced into them.
"""

import pgvector.sqlalchemy
from alembic import op

revision = "0002_embedding_1024"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

#: Width before and after. A document is a cache of its source, so the rows are dropped.
OLD = 1536
NEW = 1024


def _resize(width: int) -> None:
    op.execute("DELETE FROM documents")
    op.alter_column(
        "documents",
        "embedding",
        type_=pgvector.sqlalchemy.Vector(dim=width),
        existing_nullable=False,
        postgresql_using=f"embedding::vector({width})",
    )


def upgrade():
    _resize(NEW)


def downgrade():
    _resize(OLD)
