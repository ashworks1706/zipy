"""Assembles the context of one request from the three memory layers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from engine.core.config import Collaboration, Files, Memory
from engine.core.protocols import (
    CollaborationStore,
    ConversationSource,
    DocumentStore,
    Embedder,
    OrgContextStore,
    Sandbox,
)
from engine.core.types import (
    ChatMessage,
    Conditioning,
    IngestError,
    Provenance,
    RecallHit,
    RequestContext,
    Signal,
)
from engine.memory import follow_up
from engine.memory.collaboration import render as render_collaborator
from engine.memory.ingest import files as file_reader
from engine.memory.ingest.pipeline import ingest
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
    #: What the files attached to this message say. Empty when none were, or none could be read.
    attachments: str = ""


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
        conditioning: Conditioning = Conditioning.TEXT,
        model: str = "",
        files: Files | None = None,
        sandbox: Sandbox | None = None,
    ) -> None:
        self._memory = memory
        self._conversation = conversation
        self._org_context = org_context
        self._embedder = embedder
        self._documents = documents
        self._collaboration = collaboration
        self._settings = settings
        self._conditioning = conditioning
        self._model = model
        self._files = files or Files()
        self._sandbox = sandbox

    async def build(self, ctx: RequestContext, message: str) -> Context:
        """The last conversation_limit messages, the org's facts, and recall if triggered."""
        history = await self._conversation.recent(ctx.channel, self._memory.conversation_limit)
        facts = await self._org_context.facts(ctx.org_id)
        recalled: list[RecallHit] = []
        if wants_recall(message, self._memory.recall_triggers):
            recalled = await recall(ctx, message, self._memory, self._embedder, self._documents)
        await self._read_turn(ctx, message, history)
        return Context(
            history=history,
            org_facts=render(facts),
            recalled=recalled,
            collaborator=await self._collaborator(ctx),
            attachments=await self.read_files(ctx),
        )

    async def read_files(self, ctx: RequestContext) -> str:
        """Read every attached file into text, store it for later, and return what this turn sees.

        A file that cannot be read says so in one line rather than failing the request: the rest of
        the message is still worth answering.
        """
        if not self._files.enabled or not ctx.files:
            return ""
        blocks: list[str] = []
        for attachment in ctx.files[: self._files.max_per_message]:
            name = attachment.name or attachment.media_type
            try:
                document = await file_reader.read(
                    attachment, self._files, ctx=ctx, sandbox=self._sandbox
                )
                await ingest(ctx.org_id, document, self._memory, self._embedder, self._documents)
            except IngestError as exc:
                blocks.append(f"{name}: {exc}")
                continue
            blocks.append(f"{name}\n{document.text[: self._files.max_prompt_chars]}")
        return "\n\n".join(blocks)

    async def _read_turn(
        self, ctx: RequestContext, message: str, history: list[ChatMessage]
    ) -> None:
        """Record what a follow-up turn shows before the state is read for this request."""
        if not self._settings.enabled:
            return
        signals = follow_up.read(
            message,
            history,
            self._settings.brevity_triggers,
            self._settings.detail_triggers,
            self._settings.correction_triggers,
        )
        await self.observe(ctx, signals)

    async def _collaborator(self, ctx: RequestContext) -> str:
        """What the asker's state asks for, or nothing while collaboration is off."""
        if not self._settings.enabled:
            return ""
        state = await self._collaboration.state(ctx.org_id, ctx.member)
        return render_collaborator(state, self._settings.min_observations, self._conditioning)

    async def observe(self, ctx: RequestContext, signals: Sequence[Signal]) -> None:
        """Records what a turn showed about the asker. Does nothing while collaboration is off."""
        if not self._settings.enabled or not signals:
            return
        await self._collaboration.observe(
            ctx.org_id,
            ctx.member,
            signals,
            Provenance(request_id=ctx.request_id, arm=self._settings.arm, model=self._model),
        )
