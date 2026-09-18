"""Assembles the context of one request from the three memory layers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from engine.core.config import Collaboration, Memory
from engine.core.protocols import (
    CollaborationStore,
    ConversationSource,
    DocumentStore,
    Embedder,
    OrgContextStore,
)
from engine.core.types import ChatMessage, RecallHit, RequestContext, Signal
from engine.memory.collaboration import render as render_collaborator
from engine.memory.org_context import render
from engine.memory.recall import recall
from engine.memory.triggers import wants_recall


@dataclass(frozen=True)
class Context:
    """Everything memory gives the prompt builder for one request."""

    history: list[ChatMessage]
    org_facts: str
    recalled: list[RecallHit]
    #: What the asker's collaboration state asks for. Empty when it is off or says nothing yet.
    collaborator: str = ""


class MemoryManager:
    """Reads conversation, org facts, the asker's state and, when triggered, recall."""

    def __init__(
        self,
        memory: Memory,
        conversation: ConversationSource,
        org_context: OrgContextStore,
        embedder: Embedder,
        documents: DocumentStore,
        collaboration: CollaborationStore,
        settings: Collaboration,
    ) -> None:
        self._memory = memory
        self._conversation = conversation
        self._org_context = org_context
        self._embedder = embedder
        self._documents = documents
        self._collaboration = collaboration
        self._settings = settings

    async def build(self, ctx: RequestContext, message: str) -> Context:
        """The last conversation_limit messages, the org's facts, and recall if triggered."""
        history = await self._conversation.recent(ctx.channel, self._memory.conversation_limit)
        facts = await self._org_context.facts(ctx.org_id)
        recalled: list[RecallHit] = []
        if wants_recall(message, self._memory.recall_triggers):
            recalled = await recall(ctx, message, self._memory, self._embedder, self._documents)
        return Context(
            history=history,
            org_facts=render(facts),
            recalled=recalled,
            collaborator=await self._collaborator(ctx),
        )

    async def _collaborator(self, ctx: RequestContext) -> str:
        """What the asker's state asks for, or nothing while collaboration is off."""
        if not self._settings.enabled:
            return ""
        state = await self._collaboration.state(ctx.org_id, ctx.member)
        return render_collaborator(state, self._settings.min_observations)

    async def observe(self, ctx: RequestContext, signals: Sequence[Signal]) -> None:
        """Records what a turn showed about the asker. Does nothing while collaboration is off."""
        if not self._settings.enabled or not signals:
            return
        await self._collaboration.observe(ctx.org_id, ctx.member, signals)
