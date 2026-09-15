"""Assembles the context of one request from the three memory layers."""

from __future__ import annotations

from dataclasses import dataclass

from engine.core.config import Memory
from engine.core.protocols import ConversationSource, DocumentStore, Embedder, OrgContextStore
from engine.core.types import ChatMessage, RecallHit, RequestContext
from engine.memory.org_context import render
from engine.memory.recall import recall
from engine.memory.triggers import wants_recall


@dataclass(frozen=True)
class Context:
    """Everything memory gives the prompt builder for one request."""

    history: list[ChatMessage]
    org_facts: str
    recalled: list[RecallHit]


class MemoryManager:
    """Reads conversation, org facts and, when triggered, recall."""

    def __init__(
        self,
        memory: Memory,
        conversation: ConversationSource,
        org_context: OrgContextStore,
        embedder: Embedder,
        documents: DocumentStore,
    ) -> None:
        self._memory = memory
        self._conversation = conversation
        self._org_context = org_context
        self._embedder = embedder
        self._documents = documents

    async def build(self, ctx: RequestContext, message: str) -> Context:
        """The last conversation_limit messages, the org's facts, and recall if triggered."""
        history = await self._conversation.recent(ctx.channel, self._memory.conversation_limit)
        facts = await self._org_context.facts(ctx.org_id)
        recalled: list[RecallHit] = []
        if wants_recall(message, self._memory.recall_triggers):
            recalled = await recall(ctx, message, self._memory, self._embedder, self._documents)
        return Context(history=history, org_facts=render(facts), recalled=recalled)
