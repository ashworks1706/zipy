"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-15

The tables of engine/data/tables.py. The IVFFlat index on documents.embedding is not created
here; it is added once the table holds data, as docs/ROADMAP.md says.
"""

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "orgs",
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("setup_complete", sa.Boolean(), nullable=False),
        sa.Column("budget_cents", sa.Integer(), nullable=False),
        sa.Column("spent_cents", sa.Double(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("org_id"),
    )

    op.create_table(
        "workspaces",
        sa.Column("platform", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("notice_channel_id", sa.String(length=64), nullable=False),
        sa.Column("bot_token", sa.LargeBinary(), nullable=True),
        sa.Column("installed_by", sa.String(length=64), nullable=False),
        sa.Column(
            "installed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.org_id"]),
        sa.PrimaryKeyConstraint("platform", "workspace_id"),
    )
    op.create_index(op.f("ix_workspaces_org_id"), "workspaces", ["org_id"], unique=False)

    op.create_table(
        "members",
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.org_id"]),
        sa.PrimaryKeyConstraint("org_id", "platform", "user_id"),
    )

    op.create_table(
        "credentials",
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("access_token", sa.LargeBinary(), nullable=False),
        sa.Column("refresh_token", sa.LargeBinary(), nullable=True),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("connected_by_platform", sa.String(length=64), nullable=False),
        sa.Column("connected_by_user", sa.String(length=64), nullable=False),
        sa.Column("valid", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.org_id"]),
        sa.PrimaryKeyConstraint("org_id", "provider"),
    )

    op.create_table(
        "org_context",
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.org_id"]),
        sa.PrimaryKeyConstraint("org_id", "key"),
    )

    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=200), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(dim=1536), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.org_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("documents_scope", "documents", ["org_id", "source", "source_id"], unique=False)

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("actor_platform", sa.String(length=64), nullable=False),
        sa.Column("actor_user", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("target", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.org_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_log_org_id"), "audit_log", ["org_id"], unique=False)

    op.create_table(
        "org_tool_config",
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("tool_name", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("config_overrides", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.org_id"]),
        sa.PrimaryKeyConstraint("org_id", "tool_name"),
    )

    op.create_table(
        "pending_confirmations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("channel_id", sa.String(length=64), nullable=False),
        sa.Column("thread_id", sa.String(length=64), nullable=False),
        sa.Column("requested_by", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.org_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_pending_confirmations_expires_at"),
        "pending_confirmations",
        ["expires_at"],
        unique=False,
    )


def downgrade():
    op.drop_index(op.f("ix_pending_confirmations_expires_at"), table_name="pending_confirmations")
    op.drop_table("pending_confirmations")
    op.drop_table("org_tool_config")
    op.drop_index(op.f("ix_audit_log_org_id"), table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index("documents_scope", table_name="documents")
    op.drop_table("documents")
    op.drop_table("org_context")
    op.drop_table("credentials")
    op.drop_table("members")
    op.drop_index(op.f("ix_workspaces_org_id"), table_name="workspaces")
    op.drop_table("workspaces")
    op.drop_table("orgs")
