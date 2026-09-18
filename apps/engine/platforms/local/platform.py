"""The local platform: one conversation in a terminal, as plain text or JSON lines.

Its workspace is local, its member is the developer at the keyboard with the admin role, and its
org is created on first run. Confirmations are answered by typing, or by the console's keys.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict

from engine.core.config import Budget
from engine.core.types import (
    ChannelRef,
    ChatMessage,
    MemberRef,
    PlatformError,
    RequestContext,
    Speaker,
    WorkspaceRef,
    ZipyError,
)
from engine.gateway.gateway import Gateway
from engine.gateway.messages import (
    Answer,
    Capabilities,
    ConfirmPrompt,
    Inbound,
    InboundAnswer,
    Outbound,
    Text,
    WorkspaceInstalled,
)
from engine.platforms.base import BasePlatform
from engine.platforms.local.protocol import decode, encode
from engine.telemetry.trace import record

WORKSPACE = WorkspaceRef(platform="local", workspace_id="local")
CHANNEL = "terminal"
ANSWERS: dict[str, Answer] = {"confirm": Answer.CONFIRM, "cancel": Answer.CANCEL}

ReadLine = Callable[[], Awaitable[str]]
WriteLine = Callable[[str], None]
Stats = Callable[[], dict[str, float]]


async def stdin_line() -> str:
    """One line from stdin, empty at end of input."""
    return await asyncio.to_thread(sys.stdin.readline)


def stdout_line(line: str) -> None:
    """One line on stdout."""
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


class LocalSettings(BaseModel):
    """[platforms.local] settings."""

    model_config = ConfigDict(extra="forbid")

    jsonl: bool = False
    org_name: str = "Local dev org"
    member_name: str = "developer"
    message_limit: int = 100_000


class LocalPlatform(BasePlatform[LocalSettings]):
    """Reads stdin, writes stdout. Keeps its own conversation in memory for recent()."""

    name: ClassVar[str] = "local"
    settings_model: ClassVar[type[BaseModel]] = LocalSettings

    def __init__(
        self,
        settings: LocalSettings,
        gateway: Gateway,
        *,
        read_line: ReadLine | None = None,
        write_line: WriteLine | None = None,
        stats: Stats | None = None,
        budget: Budget | None = None,
    ) -> None:
        super().__init__(settings, gateway)
        self._read_line = read_line or stdin_line
        self._write_line = write_line or stdout_line
        self._stats = stats
        self._budget = budget or Budget()
        self._turn = 0
        self._history: list[ChatMessage] = []
        self._pending = ""

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            markup="markdown",
            message_limit=self.settings.message_limit,
            buttons=self.settings.jsonl,
            threads=False,
            direct_messages=True,
        )

    @property
    def channel(self) -> ChannelRef:
        """The conversation being typed in. A new conversation is a new channel."""
        return ChannelRef(workspace=WORKSPACE, channel_id=f"{CHANNEL}-{self._turn}")

    @property
    def member(self) -> MemberRef:
        """The developer at the keyboard."""
        return MemberRef(platform="local", user_id=self.settings.member_name)

    async def run(self) -> None:
        """Read lines until stdin closes; each ask goes to the gateway, each reply is written."""
        await self._link()
        if self.settings.jsonl:
            self._write_line(encode("ready"))
        while True:
            line = await self._read_line()
            if not line:
                return
            await self.handle(line.rstrip("\n"))

    async def handle(self, line: str) -> None:
        """One line of input, as a JSON line or as typed text."""
        if self.settings.jsonl:
            await self._handle_json(line)
            return
        text = line.strip()
        if not text:
            return
        answer = ANSWERS.get(text.lower())
        if self._pending and answer is not None:
            await self.answer(answer)
            return
        await self.ask(text)

    async def _handle_json(self, line: str) -> None:
        message = decode(line)
        if message is None:
            self._write_line(encode("error", message="not a JSON line with a known op"))
            return
        op = message["op"]
        if op == "ask":
            await self.ask(str(message.get("text", "")))
        elif op == "confirm":
            await self.answer(Answer.CONFIRM if message.get("approve") else Answer.CANCEL)
        elif op == "new":
            self.reset()
        else:
            self.stats()

    async def ask(self, text: str) -> None:
        """Hand one message to the gateway and write what comes back."""
        if not text:
            self._write_line(encode("error", message="ask needs text"))
            return
        inbound = Inbound(
            channel=self.channel,
            member=self.member,
            display_name=self.settings.member_name,
            text=text,
            direct=True,
            received_at=datetime.now(UTC),
        )
        self._history.append(
            ChatMessage(
                speaker=Speaker.USER,
                content=text,
                name=self.settings.member_name,
                at=inbound.received_at,
            )
        )
        try:
            await self._deliver(await self._message(inbound))
        except ZipyError as exc:
            self._fail(exc)

    async def _link(self) -> None:
        """Give this workspace an org on first run, with the developer as its admin."""
        if await self.gateway.linked(WORKSPACE):
            return
        install = WorkspaceInstalled(
            channel=self.channel, installed_by=self.member, name=self.settings.org_name
        )
        await self._deliver(await self.gateway.installed(install, self._budget))

    async def _message(self, inbound: Inbound) -> list[Outbound]:
        """The gateway's reply."""
        return await self.gateway.message(inbound, self.capabilities)

    async def answer(self, answer: Answer) -> None:
        """Answer the confirmation this conversation is holding."""
        if not self._pending:
            self._write_line(encode("error", message="nothing is waiting for an answer"))
            return
        event = InboundAnswer(
            channel=self.channel,
            member=self.member,
            confirmation_id=self._pending,
            answer=answer,
            received_at=datetime.now(UTC),
        )
        self._pending = ""
        try:
            await self._deliver(await self.gateway.answer(event, self.capabilities))
        except ZipyError as exc:
            self._fail(exc)

    def reset(self) -> None:
        """Start a new conversation: a new channel, an empty history, nothing pending."""
        self._turn += 1
        self._history.clear()
        self._pending = ""
        if self.settings.jsonl:
            self._write_line(encode("ready"))

    def stats(self) -> None:
        """Write the metrics snapshot the console draws its pane from."""
        if self._stats is None:
            self._write_line(encode("error", message="no metrics snapshot is attached"))
            return
        self._write_line(encode("stats", stats=self._stats()))

    def event(self, ctx: RequestContext, name: str, data: dict[str, Any]) -> None:
        """TraceSink: one trace event per line while the console is watching."""
        if self.settings.jsonl:
            self._write_line(encode("event", event=record(ctx, name, data, datetime.now(UTC))))

    def _fail(self, exc: ZipyError) -> None:
        self._write_line(encode("error", message=str(exc)) if self.settings.jsonl else str(exc))

    async def _deliver(self, outbound: list[Outbound]) -> None:
        for one in outbound:
            await self.send(one)

    async def send(self, outbound: Outbound) -> None:
        if outbound.channel != self.channel:
            raise PlatformError(f"local has no conversation {outbound.channel.channel_id}")
        if isinstance(outbound, ConfirmPrompt):
            self._prompt(outbound)
            return
        self._text(outbound)

    def _text(self, outbound: Text) -> None:
        self._history.append(
            ChatMessage(speaker=Speaker.ASSISTANT, content=outbound.text, at=datetime.now(UTC))
        )
        if not self.settings.jsonl:
            self._write_line(outbound.text)
            return
        self._write_line(
            encode(
                "result",
                result={"text": outbound.text, "private": outbound.private_to is not None},
            )
        )

    def _prompt(self, prompt: ConfirmPrompt) -> None:
        self._pending = prompt.confirmation_id
        if not self.settings.jsonl:
            self._write_line(prompt.summary)
            return
        self._write_line(
            encode(
                "result",
                result={
                    "text": prompt.summary,
                    "confirmation_id": prompt.confirmation_id,
                    "answers": [Answer.CONFIRM.value, Answer.CANCEL.value],
                    "expires_at": prompt.expires_at,
                },
            )
        )

    async def recent(self, channel: ChannelRef, limit: int) -> list[ChatMessage]:
        if channel != self.channel:
            raise PlatformError(f"local has no conversation {channel.channel_id}")
        return self._history[-limit:] if limit > 0 else []
