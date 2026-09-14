"""Stored records: credentials, audit entries, documents and chunks, background jobs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import SecretStr

from engine.core.types.identity import MemberRef, OrgId


@dataclass(frozen=True)
class ProviderAuth:
    """A decrypted credential for one org and provider. Never shown to the model."""

    org_id: OrgId
    provider: str
    access_token: SecretStr
    scopes: tuple[str, ...]
    expires_at: datetime | None
    refresh_token: SecretStr | None = None


@dataclass(frozen=True)
class AuditEntry:
    """One tool execution. Append-only."""

    org_id: OrgId
    actor: MemberRef
    action: str
    target: str
    payload: dict[str, Any]
    ok: bool
    error: str
    at: datetime


@dataclass(frozen=True)
class Document:
    """One searchable document a tool produced: a transcript, a page, a file."""

    source: str
    source_id: str
    title: str
    text: str
    updated_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Chunk:
    """One piece of a document, about memory.chunk_tokens long."""

    org_id: OrgId
    source: str
    source_id: str
    index: int
    title: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RecallHit:
    """A chunk and how close it is to the query."""

    chunk: Chunk
    similarity: float


@dataclass(frozen=True)
class Job:
    """One queued unit of background work for one org. kind names the handler."""

    kind: str
    org_id: OrgId
    payload: dict[str, Any] = field(default_factory=dict)
