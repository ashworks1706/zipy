"""Assembles the context of one request from the three memory layers."""

from __future__ import annotations

from dataclasses import dataclass

from engine.core.config import Memory
from engine.core.protocols import ConversationSource, DocumentStore, Embedder, OrgContextStore
from engine.core.types import ChatMessage, RecallHit, RequestContext


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
        raise NotImplementedError
