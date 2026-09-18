"""The seams. Every replaceable dependency is a protocol here with a double in doubles.py.

Plugins are not here: platforms, providers and tools each extend a base class in their own
package and are discovered by engine.core.plugins.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol

from engine.core.types import (
    AuditEntry,
    ChannelRef,
    ChatMessage,
    Chunk,
    CollaborationState,
    Completion,
    Job,
    MemberRef,
    Org,
    OrgFact,
    OrgId,
    OrgToolConfig,
    PendingConfirmation,
    ProviderAuth,
    RecallHit,
    RequestContext,
    Role,
    Signal,
    Workspace,
    WorkspaceRef,
)


class ChatModel(Protocol):
    """A chat model with function calling."""

    async def complete(
        self,
        ctx: RequestContext,
        messages: Sequence[ChatMessage],
        tools: Sequence[dict[str, Any]],
    ) -> Completion: ...


class Embedder(Protocol):
    """Text to vectors, one per input."""

    async def embed(self, org_id: OrgId, texts: Sequence[str]) -> list[list[float]]: ...


class ConversationSource(Protocol):
    """The recent messages of a conversation. The platform is the store; Zipy keeps none."""

    async def recent(self, channel: ChannelRef, limit: int) -> list[ChatMessage]: ...


class Notifier(Protocol):
    """Posts a notice to every workspace of an org, in its notice channel."""

    async def notify(self, org_id: OrgId, text: str) -> None: ...


class OrgStore(Protocol):
    """Orgs, their members' roles, and their spend."""

    async def get(self, org_id: OrgId) -> Org | None: ...

    async def create(self, name: str, budget_cents: int) -> Org: ...

    async def role(self, org_id: OrgId, member: MemberRef) -> Role: ...

    async def set_role(self, org_id: OrgId, member: MemberRef, role: Role) -> None: ...

    async def add_spend(self, org_id: OrgId, cents: float) -> None: ...

    async def reset_spend(self) -> None: ...


class WorkspaceStore(Protocol):
    """Which org each platform workspace belongs to."""

    async def get(self, ref: WorkspaceRef) -> Workspace | None: ...

    async def link(self, workspace: Workspace) -> None: ...

    async def unlink(self, ref: WorkspaceRef) -> None: ...

    async def of_org(self, org_id: OrgId) -> list[Workspace]: ...


class CollaborationStore(Protocol):
    """How each person works with the agent. Holds scores and counts, never conversation text."""

    async def state(self, org_id: OrgId, member: MemberRef) -> CollaborationState: ...

    async def observe(
        self, org_id: OrgId, member: MemberRef, signals: Sequence[Signal]
    ) -> None: ...

    async def forget(self, org_id: OrgId, member: MemberRef) -> None: ...


class OrgContextStore(Protocol):
    """Persistent facts about an org."""

    async def facts(self, org_id: OrgId) -> list[OrgFact]: ...

    async def remember(self, org_id: OrgId, fact: OrgFact) -> None: ...

    async def forget(self, org_id: OrgId, key: str) -> None: ...


class DocumentStore(Protocol):
    """Embedded document chunks, searched by similarity within one org."""

    async def replace(
        self,
        org_id: OrgId,
        source: str,
        source_id: str,
        chunks: Sequence[Chunk],
        embeddings: Sequence[Sequence[float]],
    ) -> None: ...

    async def search(
        self,
        org_id: OrgId,
        embedding: Sequence[float],
        top_k: int,
        min_similarity: float,
        sources: Sequence[str] = (),
    ) -> list[RecallHit]: ...

    async def prune(self, source: str, older_than: datetime) -> int: ...


class CredentialStore(Protocol):
    """Encrypted provider credentials, decrypted only on read."""

    async def get(self, org_id: OrgId, provider: str) -> ProviderAuth | None: ...

    async def put(self, auth: ProviderAuth, connected_by: MemberRef) -> None: ...

    async def connected(self, org_id: OrgId) -> frozenset[str]: ...

    async def expiring(self, before: datetime) -> list[ProviderAuth]: ...

    async def mark_invalid(self, org_id: OrgId, provider: str) -> None: ...


class ToolConfigStore(Protocol):
    """Per-org tool overrides."""

    async def overrides(self, org_id: OrgId) -> dict[str, OrgToolConfig]: ...

    async def set(self, org_id: OrgId, config: OrgToolConfig) -> None: ...


class AuditLog(Protocol):
    """The append-only record of tool executions."""

    async def append(self, entry: AuditEntry) -> None: ...


class ConfirmationStore(Protocol):
    """Destructive calls waiting for an answer."""

    async def put(self, pending: PendingConfirmation) -> None: ...

    async def take(self, confirmation_id: str, now: datetime) -> PendingConfirmation | None: ...

    async def purge_expired(self, now: datetime) -> int: ...


class RateLimiter(Protocol):
    """Messages per member per minute, per org."""

    async def allow(self, org_id: OrgId, member: MemberRef) -> bool: ...


class ProviderLimiter(Protocol):
    """How often one org may call one provider."""

    async def acquire(self, org_id: OrgId, provider: str, max_wait: float) -> None: ...


class JobQueue(Protocol):
    """Background work handed from the API and the gateway to the workers."""

    async def enqueue(self, job: Job) -> None: ...

    async def next(self) -> Job | None: ...


class TraceSink(Protocol):
    """Where every model call, tool call and result of a request is recorded."""

    def event(self, ctx: RequestContext, name: str, data: dict[str, Any]) -> None: ...
