"""The schema. Alembic autogenerates migrations from these. org_id scopes every table.

Platform, workspace, channel and user ids are the platform's own strings. Provider and source
names are plugin names. Neither is an enum in the database, so a new plugin needs no migration.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Must equal models.embedding.dimensions in zipy.toml; a change is a migration and a re-embed.
# test_data.py holds the two to each other.
EMBEDDING_DIMENSIONS = 1024

ID = String(64)


class Base(DeclarativeBase):
    """The declarative base of every table."""


class OrgRow(Base):
    """One tenant."""

    __tablename__ = "orgs"

    org_id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    setup_complete: Mapped[bool] = mapped_column(default=False)
    budget_cents: Mapped[int]
    spent_cents: Mapped[float] = mapped_column(Double, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkspaceRow(Base):
    """A platform workspace linked to an org. bot_token is sealed; empty for platforms with one
    global token."""

    __tablename__ = "workspaces"

    platform: Mapped[str] = mapped_column(ID, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ID, primary_key=True)
    org_id: Mapped[UUID] = mapped_column(ForeignKey("orgs.org_id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    notice_channel_id: Mapped[str] = mapped_column(ID, default="")
    bot_token: Mapped[bytes | None] = mapped_column(LargeBinary)
    installed_by: Mapped[str] = mapped_column(ID)
    installed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MemberRow(Base):
    """A person's role in an org, per platform identity."""

    __tablename__ = "members"

    org_id: Mapped[UUID] = mapped_column(ForeignKey("orgs.org_id"), primary_key=True)
    platform: Mapped[str] = mapped_column(ID, primary_key=True)
    user_id: Mapped[str] = mapped_column(ID, primary_key=True)
    role: Mapped[str] = mapped_column(String(16))


class CredentialRow(Base):
    """One org's sealed tokens for one provider."""

    __tablename__ = "credentials"

    org_id: Mapped[UUID] = mapped_column(ForeignKey("orgs.org_id"), primary_key=True)
    provider: Mapped[str] = mapped_column(ID, primary_key=True)
    access_token: Mapped[bytes] = mapped_column(LargeBinary)
    refresh_token: Mapped[bytes | None] = mapped_column(LargeBinary)
    scopes: Mapped[list[str]] = mapped_column(JSONB, default=list)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    connected_by_platform: Mapped[str] = mapped_column(ID)
    connected_by_user: Mapped[str] = mapped_column(ID)
    valid: Mapped[bool] = mapped_column(default=True)


class OrgContextRow(Base):
    """One persistent fact about an org."""

    __tablename__ = "org_context"

    org_id: Mapped[UUID] = mapped_column(ForeignKey("orgs.org_id"), primary_key=True)
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    category: Mapped[str] = mapped_column(String(32))
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MemberStateRow(Base):
    """How one person works with the agent, as scores.

    No text column, ever. The state is what was read from behaviour, never what was said, and a
    column that could hold a quote would make the promise unkeepable. test_data.py holds this.
    """

    __tablename__ = "member_state"

    org_id: Mapped[UUID] = mapped_column(ForeignKey("orgs.org_id"), primary_key=True)
    platform: Mapped[str] = mapped_column(ID, primary_key=True)
    user_id: Mapped[str] = mapped_column(ID, primary_key=True)
    scores: Mapped[dict[str, float]] = mapped_column(JSONB, default=dict)
    observations: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DocumentRow(Base):
    """One embedded chunk of a document a tool produced."""

    __tablename__ = "documents"
    __table_args__ = (
        Index("documents_scope", "org_id", "source", "source_id"),
        Index(
            "documents_embedding",
            "embedding",
            postgresql_using="ivfflat",
            postgresql_with={"lists": 100},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    org_id: Mapped[UUID] = mapped_column(ForeignKey("orgs.org_id"))
    source: Mapped[str] = mapped_column(ID)
    source_id: Mapped[str] = mapped_column(String(200))
    chunk_index: Mapped[int]
    title: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    source_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditRow(Base):
    """One tool execution. Rows are never updated or deleted."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    org_id: Mapped[UUID] = mapped_column(ForeignKey("orgs.org_id"), index=True)
    actor_platform: Mapped[str] = mapped_column(ID)
    actor_user: Mapped[str] = mapped_column(ID)
    action: Mapped[str] = mapped_column(String(100))
    target: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    ok: Mapped[bool]
    error: Mapped[str] = mapped_column(Text, default="")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OrgToolConfigRow(Base):
    """One org's override of one tool."""

    __tablename__ = "org_tool_config"

    org_id: Mapped[UUID] = mapped_column(ForeignKey("orgs.org_id"), primary_key=True)
    tool_name: Mapped[str] = mapped_column(ID, primary_key=True)
    enabled: Mapped[bool]
    config_overrides: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class PendingConfirmationRow(Base):
    """A destructive call waiting for an answer, consumed once."""

    __tablename__ = "pending_confirmations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    org_id: Mapped[UUID] = mapped_column(ForeignKey("orgs.org_id"))
    platform: Mapped[str] = mapped_column(ID)
    workspace_id: Mapped[str] = mapped_column(ID)
    channel_id: Mapped[str] = mapped_column(ID)
    thread_id: Mapped[str] = mapped_column(ID, default="")
    requested_by: Mapped[str] = mapped_column(ID)
    action: Mapped[str] = mapped_column(String(100))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB)
    summary: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    # The sub-agent that asked, when one did: its task, tools, turns and messages so far. Null
    # when the request itself asked. The row is deleted when the answer comes and swept when it
    # expires, so this holds a conversation for as long as a confirmation waits and no longer.
    sub_agent: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
