"""In-memory doubles for every protocol in protocols.py. Tests use these; production never does."""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any
from uuid import uuid4

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
    SandboxOutput,
    SandboxRequest,
    SandboxSession,
    Signal,
    Workspace,
    WorkspaceRef,
)
from engine.core.types.collaboration import apply_signals


@dataclass
class ScriptedModel:
    """Returns the scripted completions in order and records every request."""

    script: list[Completion]
    requests: list[list[ChatMessage]] = field(default_factory=list)

    async def complete(
        self,
        ctx: RequestContext,  # noqa: ARG002 - protocol signature
        messages: Sequence[ChatMessage],
        tools: Sequence[dict[str, Any]],  # noqa: ARG002 - protocol signature
    ) -> Completion:
        self.requests.append(list(messages))
        return self.script.pop(0)


@dataclass
class FixedEmbedder:
    """Embeds every text as the same vector."""

    vector: list[float]

    async def embed(
        self,
        org_id: OrgId,  # noqa: ARG002 - protocol signature
        texts: Sequence[str],
    ) -> list[list[float]]:
        return [list(self.vector) for _ in texts]


@dataclass
class MemoryConversation:
    """Conversation histories held in a dict."""

    channels: dict[ChannelRef, list[ChatMessage]] = field(default_factory=dict)

    async def recent(self, channel: ChannelRef, limit: int) -> list[ChatMessage]:
        return self.channels.get(channel, [])[-limit:] if limit else []


@dataclass
class MemoryNotifier:
    """Notices held in a list."""

    sent: list[tuple[OrgId, str]] = field(default_factory=list)

    async def notify(self, org_id: OrgId, text: str) -> None:
        self.sent.append((org_id, text))


@dataclass
class MemoryOrgs:
    """Orgs and roles held in dicts."""

    orgs: dict[OrgId, Org] = field(default_factory=dict)
    roles: dict[tuple[OrgId, MemberRef], Role] = field(default_factory=dict)

    async def get(self, org_id: OrgId) -> Org | None:
        return self.orgs.get(org_id)

    async def create(self, name: str, budget_cents: int) -> Org:
        org = Org(OrgId(str(uuid4())), name, False, budget_cents, 0)
        self.orgs[org.org_id] = org
        return org

    async def role(self, org_id: OrgId, member: MemberRef) -> Role:
        return self.roles.get((org_id, member), Role.MEMBER)

    async def set_role(self, org_id: OrgId, member: MemberRef, role: Role) -> None:
        self.roles[(org_id, member)] = role

    async def add_spend(self, org_id: OrgId, cents: float) -> None:
        org = self.orgs[org_id]
        self.orgs[org_id] = replace(org, spent_cents=org.spent_cents + cents)

    async def reset_spend(self) -> None:
        self.orgs = {k: replace(o, spent_cents=0.0) for k, o in self.orgs.items()}


@dataclass
class MemoryWorkspaces:
    """Workspace links held in a dict."""

    links: dict[WorkspaceRef, Workspace] = field(default_factory=dict)

    async def get(self, ref: WorkspaceRef) -> Workspace | None:
        return self.links.get(ref)

    async def link(self, workspace: Workspace) -> None:
        self.links[workspace.ref] = workspace

    async def unlink(self, ref: WorkspaceRef) -> None:
        self.links.pop(ref, None)

    async def of_org(self, org_id: OrgId) -> list[Workspace]:
        return [w for w in self.links.values() if w.org_id == org_id]


@dataclass
class MemoryCollaboration:
    """Collaboration state held in a dict."""

    by_member: dict[tuple[OrgId, MemberRef], CollaborationState] = field(default_factory=dict)

    async def state(self, org_id: OrgId, member: MemberRef) -> CollaborationState:
        return self.by_member.get((org_id, member), CollaborationState(member=member))

    async def observe(self, org_id: OrgId, member: MemberRef, signals: Sequence[Signal]) -> None:
        current = await self.state(org_id, member)
        self.by_member[(org_id, member)] = apply_signals(current, signals)

    async def forget(self, org_id: OrgId, member: MemberRef) -> None:
        self.by_member.pop((org_id, member), None)


@dataclass
class MemoryOrgContext:
    """Org facts held in a dict."""

    by_org: dict[OrgId, dict[str, OrgFact]] = field(default_factory=dict)

    async def facts(self, org_id: OrgId) -> list[OrgFact]:
        return list(self.by_org.get(org_id, {}).values())

    async def remember(self, org_id: OrgId, fact: OrgFact) -> None:
        self.by_org.setdefault(org_id, {})[fact.key] = fact

    async def forget(self, org_id: OrgId, key: str) -> None:
        self.by_org.get(org_id, {}).pop(key, None)


@dataclass
class MemoryDocuments:
    """Chunks held in a list; search returns every chunk of the org at similarity 1."""

    chunks: list[Chunk] = field(default_factory=list)

    async def replace(
        self,
        org_id: OrgId,
        source: str,
        source_id: str,
        chunks: Sequence[Chunk],
        embeddings: Sequence[Sequence[float]],  # noqa: ARG002 - protocol signature
    ) -> None:
        self.chunks = [
            c
            for c in self.chunks
            if (c.org_id, c.source, c.source_id) != (org_id, source, source_id)
        ]
        self.chunks.extend(chunks)

    async def search(
        self,
        org_id: OrgId,
        embedding: Sequence[float],  # noqa: ARG002 - protocol signature
        top_k: int,
        min_similarity: float,  # noqa: ARG002 - protocol signature
        sources: Sequence[str] = (),
    ) -> list[RecallHit]:
        hits = [
            RecallHit(c, 1.0)
            for c in self.chunks
            if c.org_id == org_id and (not sources or c.source in sources)
        ]
        return hits[:top_k]

    async def prune(
        self,
        source: str,  # noqa: ARG002 - protocol signature
        older_than: datetime,  # noqa: ARG002 - protocol signature
    ) -> int:
        return 0


@dataclass
class MemoryCredentials:
    """Credentials held in plain text in a dict."""

    auths: dict[tuple[OrgId, str], ProviderAuth] = field(default_factory=dict)
    invalid: set[tuple[OrgId, str]] = field(default_factory=set)

    async def get(self, org_id: OrgId, provider: str) -> ProviderAuth | None:
        if (org_id, provider) in self.invalid:
            return None
        return self.auths.get((org_id, provider))

    async def put(
        self,
        auth: ProviderAuth,
        connected_by: MemberRef,  # noqa: ARG002 - protocol signature
    ) -> None:
        self.auths[(auth.org_id, auth.provider)] = auth
        self.invalid.discard((auth.org_id, auth.provider))

    async def connected(self, org_id: OrgId) -> frozenset[str]:
        return frozenset(p for (o, p) in self.auths if o == org_id and (o, p) not in self.invalid)

    async def expiring(self, before: datetime) -> list[ProviderAuth]:
        return [a for a in self.auths.values() if a.expires_at and a.expires_at < before]

    async def mark_invalid(self, org_id: OrgId, provider: str) -> None:
        self.invalid.add((org_id, provider))


@dataclass
class MemoryToolConfig:
    """Tool overrides held in a dict."""

    by_org: dict[OrgId, dict[str, OrgToolConfig]] = field(default_factory=dict)

    async def overrides(self, org_id: OrgId) -> dict[str, OrgToolConfig]:
        return dict(self.by_org.get(org_id, {}))

    async def set(self, org_id: OrgId, config: OrgToolConfig) -> None:
        self.by_org.setdefault(org_id, {})[config.tool] = config


@dataclass
class MemoryAudit:
    """Audit entries held in a list."""

    entries: list[AuditEntry] = field(default_factory=list)

    async def append(self, entry: AuditEntry) -> None:
        self.entries.append(entry)


@dataclass
class MemoryConfirmations:
    """Pending confirmations held in a dict."""

    pending: dict[str, PendingConfirmation] = field(default_factory=dict)

    async def put(self, pending: PendingConfirmation) -> None:
        self.pending[pending.id] = pending

    async def take(self, confirmation_id: str, now: datetime) -> PendingConfirmation | None:
        found = self.pending.pop(confirmation_id, None)
        return found if found and found.expires_at > now else None

    async def purge_expired(self, now: datetime) -> int:
        expired = [k for k, p in self.pending.items() if p.expires_at <= now]
        for key in expired:
            del self.pending[key]
        return len(expired)


@dataclass
class AllowAll:
    """A rate limiter that never limits."""

    async def allow(
        self,
        org_id: OrgId,  # noqa: ARG002 - protocol signature
        member: MemberRef,  # noqa: ARG002 - protocol signature
    ) -> bool:
        return True


@dataclass
class NoLimit:
    """A provider limiter that never waits and never refuses."""

    taken: list[tuple[OrgId, str]] = field(default_factory=list)

    async def acquire(
        self,
        org_id: OrgId,
        provider: str,
        max_wait: float,  # noqa: ARG002 - the double spends no time
    ) -> None:
        """Record the call and allow it."""
        self.taken.append((org_id, provider))


@dataclass
class MemoryQueue:
    """Jobs held in a deque."""

    jobs: deque[Job] = field(default_factory=deque)

    async def enqueue(self, job: Job) -> None:
        self.jobs.append(job)

    async def next(self) -> Job | None:
        return self.jobs.popleft() if self.jobs else None


@dataclass
class MemoryTrace:
    """Trace events held in a list, with the level each was raised at."""

    events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    #: One entry per event: its name, the depth it came from, and the delegate call it was under.
    levels: list[tuple[str, int, str]] = field(default_factory=list)

    def event(self, ctx: RequestContext, name: str, data: dict[str, Any]) -> None:
        self.events.append((name, data))
        self.levels.append((name, ctx.depth, ctx.parent))


@dataclass
class MemorySandbox:
    """A sandbox that records what it was asked and answers from a script."""

    answers: dict[str, SandboxOutput] = field(default_factory=dict)
    default: SandboxOutput | None = None
    ran: list[tuple[OrgId, str, str | None]] = field(default_factory=list)
    written: dict[str, bytes] = field(default_factory=dict)
    live: list[SandboxSession] = field(default_factory=list)
    killed: list[str] = field(default_factory=list)
    reaped: list[str] = field(default_factory=list)

    async def run(self, ctx: RequestContext, request: SandboxRequest) -> SandboxOutput:
        self.ran.append((ctx.org_id, request.command, request.session))
        for needle, answer in self.answers.items():
            if needle in request.command:
                return answer
        if self.default is not None:
            return self.default
        return SandboxOutput(exit_code=0, stdout="", stderr="", session=request.session)

    async def put(self, ctx: RequestContext, session: str, name: str, content: bytes) -> str:
        self.written[f"{ctx.org_id}/{session}/{name}"] = content
        return f"/tmp/{name}"

    async def sessions(self, org_id: OrgId | None = None) -> list[SandboxSession]:
        return [s for s in self.live if org_id is None or s.org_id == org_id]

    async def kill(self, name: str) -> bool:
        self.killed.append(name)
        before = len(self.live)
        self.live = [s for s in self.live if s.name != name]
        return len(self.live) < before

    async def reap_scope(self, ctx: RequestContext) -> list[str]:
        gone = [s.name for s in self.live if s.org_id == ctx.org_id]
        self.reaped.extend(gone)
        self.live = [s for s in self.live if s.org_id != ctx.org_id]
        return gone

    async def reap_idle(self) -> list[str]:
        return []
