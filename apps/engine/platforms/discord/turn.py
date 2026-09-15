"""One turn, written into a single Discord message and edited while the engine reports it.

The card is posted before the engine starts, so the member sees the turn begin rather than
waiting in silence, and the answer replaces it at the end. Editing is paced: Discord rate limits
edits, and a card that redraws on every event would spend the allowance on the first tool call.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Sequence

import discord

from engine.gateway.messages import Outbound, Text
from engine.platforms.cards import Card
from engine.telemetry.logging import get

log = get("platforms.discord")

#: Runs the turn, given somewhere to write progress. Returns what to post when it is done.
Run = Callable[[Callable[..., None]], Awaitable[Sequence[Outbound]]]

#: Posts an outbound the card could not carry.
Send = Callable[[Outbound], Awaitable[None]]


class Turn:
    """The message a turn lives in, from the first paint to the answer."""

    def __init__(self, channel: discord.abc.Messageable, edit_every_ms: int, send: Send) -> None:
        self._channel = channel
        self._gap = edit_every_ms / 1000
        self._send = send
        self._card = Card()

    async def run(self, work: Run) -> bool:
        """Run work, showing its progress. False when no card could be posted and none was shown.

        A channel that refuses the first message is not an error the member should see: the caller
        falls back to answering once the turn is done.
        """
        posted = await self._post()
        if posted is None:
            return False
        stop = asyncio.Event()
        editor = asyncio.create_task(self._edit_until(posted, stop))
        try:
            outbound = await work(self._card.apply)
        finally:
            stop.set()
            await editor
        await self._finish(posted, outbound)
        return True

    async def _post(self) -> discord.Message | None:
        """The card message, posted empty. None when the channel refused it."""
        try:
            return await self._channel.send(self._card.running())
        except discord.DiscordException as exc:
            log.warning("discord card not posted", error=str(exc))
            return None

    async def _edit_until(self, posted: discord.Message, stop: asyncio.Event) -> None:
        """Redraw the card no more often than the gap, until the turn says stop."""
        while not stop.is_set():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self._gap)
            if not self._card.dirty:
                continue
            self._card.dirty = False
            try:
                await posted.edit(content=self._card.running())
            except discord.DiscordException as exc:
                log.warning("discord card not edited", error=str(exc))
                return

    async def _finish(self, posted: discord.Message, outbound: Sequence[Outbound]) -> None:
        """Put the answer on the card. Anything the card cannot carry posts as its own message."""
        rest = list(outbound)
        first = next((one for one in rest if isinstance(one, Text)), None)
        if first is not None:
            rest.remove(first)
            try:
                await posted.edit(content=self._card.finished(first.text))
            except discord.DiscordException as exc:
                log.warning("discord card not finished", error=str(exc))
                rest.insert(0, first)
        for one in rest:
            await self._send(one)
