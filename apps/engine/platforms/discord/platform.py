"""The discord platform."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, ClassVar, cast

import discord
from pydantic import BaseModel, ConfigDict, SecretStr

from engine.core.config import Budget
from engine.core.types import (
    Attachment,
    ChannelRef,
    ChatMessage,
    MemberRef,
    PlatformError,
    Speaker,
    WorkspaceRef,
    ZipyError,
)
from engine.gateway.gateway import Gateway
from engine.gateway.messages import (
    Capabilities,
    ConfirmPrompt,
    Inbound,
    InboundAnswer,
    Outbound,
    Text,
    WorkspaceInstalled,
)
from engine.platforms.base import BasePlatform
from engine.platforms.cards import Card
from engine.platforms.discord.render import confirm_embed, confirm_view, parse_custom_id
from engine.platforms.routing import (
    Arrival,
    Trigger,
    quoted_reply,
    thread_name,
    trigger,
)
from engine.telemetry.logging import get

log = get("platforms.discord")


class DiscordSettings(BaseModel):
    """[platforms.discord] settings. Secrets are in .env."""

    model_config = ConfigDict(extra="forbid")

    token: SecretStr = SecretStr("")
    message_limit: int = 2000
    #: Shortest gap between edits of the card while a turn runs.
    edit_every_ms: int = 1500


def intents() -> discord.Intents:
    """The gateway intents Zipy reads messages and members with."""
    wanted = discord.Intents.default()
    wanted.message_content = True
    wanted.members = True
    return wanted


def channel_ref(workspace_id: str, channel: object, channel_id: str) -> ChannelRef:
    """The conversation a channel is. A thread carries its parent channel and its own id."""
    workspace = WorkspaceRef(platform="discord", workspace_id=workspace_id)
    if isinstance(channel, discord.Thread):
        return ChannelRef(
            workspace=workspace,
            channel_id=str(channel.parent_id),
            thread_id=str(channel.id),
        )
    return ChannelRef(workspace=workspace, channel_id=channel_id)


class DiscordPlatform(BasePlatform[DiscordSettings]):
    """Discord over the gateway websocket. A server is a workspace; mentions and DMs reach Zipy."""

    name: ClassVar[str] = "discord"
    owns: ClassVar[tuple[str, ...]] = ("discord",)
    settings_model: ClassVar[type[BaseModel]] = DiscordSettings

    def __init__(
        self,
        settings: DiscordSettings,
        gateway: Gateway,
        *,
        client: discord.Client | None = None,
        budget: Budget | None = None,
    ) -> None:
        super().__init__(settings, gateway)
        self._client = client if client is not None else discord.Client(intents=intents())
        self._budget = budget or Budget()
        self._client.event(self.on_message)
        self._client.event(self.on_guild_join)
        self._client.event(self.on_interaction)

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            markup="discord-markdown",
            message_limit=self.settings.message_limit,
            buttons=True,
            threads=True,
            direct_messages=True,
        )

    async def run(self) -> None:
        """Connect to the gateway websocket and dispatch events until cancelled."""
        token = self.settings.token.get_secret_value()
        if not token:
            raise PlatformError(
                "platforms.discord has no token; set ZIPY_PLATFORMS__DISCORD__TOKEN"
            )
        try:
            await self._client.start(token)
        except discord.DiscordException as exc:
            raise PlatformError(f"discord connection failed: {exc}") from exc

    async def on_message(self, message: discord.Message) -> None:
        """A direct message, a mention that opens a thread, or a reply to Zipy inside one."""
        me = self._client.user
        if me is None or message.author.bot or message.author.id == me.id:
            return
        direct = isinstance(message.channel, discord.DMChannel)
        quoted = await self._quoted(message, me.id)
        reason = trigger(
            Arrival(
                direct=direct,
                in_thread=isinstance(message.channel, discord.Thread),
                mentions_bot=any(one.id == me.id for one in message.mentions),
                replies_to_bot=bool(quoted),
            )
        )
        if reason is None:
            return
        text = strip_mention(message.content, me.id)
        channel = message.channel
        if reason is Trigger.OPENING:
            opened = await self._open_thread(message, text)
            if opened is not None:
                channel = opened
        workspace = str(message.guild.id) if message.guild else f"dm-{message.author.id}"
        inbound = Inbound(
            channel=channel_ref(workspace, channel, str(channel.id)),
            member=MemberRef(platform=self.name, user_id=str(message.author.id)),
            display_name=message.author.display_name,
            text=text,
            direct=direct,
            received_at=message.created_at,
            platform_roles=roles_of(message.author),
            reply_to=quoted,
            images=attachments(message.attachments),
        )
        await self._answer(inbound, channel)

    async def _answer(self, inbound: Inbound, channel: discord.abc.Messageable) -> None:
        """Run the turn in one message, edited as the engine reports what it is doing.

        The card is posted before the engine starts so the member sees the turn begin, and the
        answer replaces it. A card that cannot be posted falls back to answering when it is done.
        """
        card = Card()
        posted = await self._begin(channel, card)
        if posted is None:
            await self._to_gateway(self.gateway.message(inbound, self.capabilities))
            return
        stop = asyncio.Event()
        editor = asyncio.create_task(self._editing(posted, card, stop))
        try:
            outbound = await self.gateway.message(inbound, self.capabilities, card.apply)
        except ZipyError as exc:
            log.error("discord event failed", error=str(exc))
            outbound = []
        finally:
            stop.set()
            await editor
        await self._finish(posted, card, outbound)

    async def _begin(self, channel: discord.abc.Messageable, card: Card) -> discord.Message | None:
        """The card message, posted empty. None when the channel refused it."""
        try:
            return await channel.send(card.running())
        except discord.DiscordException as exc:
            log.warning("discord card not posted", error=str(exc))
            return None

    async def _editing(self, posted: discord.Message, card: Card, stop: asyncio.Event) -> None:
        """Edit the card while the turn runs, no more often than the configured gap."""
        gap = self.settings.edit_every_ms / 1000
        while not stop.is_set():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=gap)
            if not card.dirty:
                continue
            card.dirty = False
            try:
                await posted.edit(content=card.running())
            except discord.DiscordException as exc:
                log.warning("discord card not edited", error=str(exc))
                return

    async def _finish(
        self, posted: discord.Message, card: Card, outbound: Sequence[Outbound]
    ) -> None:
        """Put the answer on the card. Anything that is not the first text posts as its own."""
        rest = list(outbound)
        first = next((one for one in rest if isinstance(one, Text)), None)
        if first is not None:
            rest.remove(first)
            try:
                await posted.edit(content=card.finished(first.text))
            except discord.DiscordException as exc:
                log.warning("discord card not finished", error=str(exc))
                rest.insert(0, first)
        for one in rest:
            await self.send(one)

    async def _open_thread(self, message: discord.Message, text: str) -> discord.Thread | None:
        """The thread the answer lives in, opened from message. None answers in the channel."""
        try:
            return await message.create_thread(name=thread_name(text))
        except discord.DiscordException as exc:
            log.warning("discord thread not opened", error=str(exc))
            return None

    async def _quoted(self, message: discord.Message, me: int) -> str:
        """The text of the Zipy message this one replies to, or empty.

        A reply to a person, or to another bot, is not a turn: the thread belongs to everyone in it.
        """
        reference = message.reference
        if reference is None:
            return ""
        replied = reference.resolved
        if replied is None and reference.message_id is not None:
            replied = await self._fetch_reference(message, reference.message_id)
        if not isinstance(replied, discord.Message):
            return ""
        return quoted_reply(str(replied.author.id), replied.content, str(me))

    async def _fetch_reference(
        self, message: discord.Message, message_id: int
    ) -> discord.Message | None:
        """The replied-to message the gateway did not resolve. None when it cannot be read."""
        try:
            return await message.channel.fetch_message(message_id)
        except discord.DiscordException as exc:
            log.warning("discord reply target unreadable", error=str(exc))
            return None

    async def on_guild_join(self, guild: discord.Guild) -> None:
        """Zipy was added to a server."""
        channel = guild.system_channel or next(iter(guild.text_channels), None)
        if channel is None or guild.owner_id is None:
            raise PlatformError(f"discord guild {guild.id} has no channel or owner to welcome")
        installed = WorkspaceInstalled(
            channel=channel_ref(str(guild.id), channel, str(channel.id)),
            installed_by=MemberRef(platform=self.name, user_id=str(guild.owner_id)),
            name=guild.name,
        )
        await self._to_gateway(self.gateway.installed(installed, self._budget))

    async def on_interaction(self, interaction: discord.Interaction) -> None:
        """A confirm or cancel button."""
        if interaction.type is not discord.InteractionType.component:
            return
        data = cast("Mapping[str, Any]", interaction.data or {})
        parsed = parse_custom_id(str(data.get("custom_id", "")))
        if parsed is None:
            return
        confirmation_id, answer = parsed
        await interaction.response.defer()
        workspace = (
            str(interaction.guild_id) if interaction.guild_id else f"dm-{interaction.user.id}"
        )
        event = InboundAnswer(
            channel=channel_ref(workspace, interaction.channel, str(interaction.channel_id)),
            member=MemberRef(platform=self.name, user_id=str(interaction.user.id)),
            confirmation_id=confirmation_id,
            answer=answer,
            received_at=interaction.created_at,
        )
        await self._to_gateway(self.gateway.answer(event, self.capabilities))

    async def send(self, outbound: Outbound) -> None:
        if isinstance(outbound, ConfirmPrompt):
            target = await self._messageable(outbound.channel)
            await self._post(
                target, embed=confirm_embed(outbound), view=confirm_view(outbound), content=None
            )
            return
        await self._send_text(outbound)

    async def _send_text(self, outbound: Text) -> None:
        if outbound.private_to is not None:
            await self._post(await self._user(outbound.private_to), content=outbound.text)
            return
        await self._post(await self._messageable(outbound.channel), content=outbound.text)

    async def recent(self, channel: ChannelRef, limit: int) -> list[ChatMessage]:
        me = self._client.user
        target = await self._messageable(channel)
        messages: list[ChatMessage] = []
        try:
            async for message in target.history(limit=limit):
                if not message.clean_content:
                    continue
                mine = me is not None and message.author.id == me.id
                messages.append(
                    ChatMessage(
                        speaker=Speaker.ASSISTANT if mine else Speaker.USER,
                        content=message.clean_content,
                        name=message.author.display_name,
                        at=message.created_at,
                    )
                )
        except discord.DiscordException as exc:
            raise PlatformError(f"discord history failed for {channel.channel_id}: {exc}") from exc
        messages.reverse()
        return messages

    async def _to_gateway(self, call: Any) -> None:
        try:
            for outbound in await call:
                await self.send(outbound)
        except ZipyError as exc:
            log.error("discord event failed", error=str(exc))

    async def _messageable(self, channel: ChannelRef) -> discord.abc.Messageable:
        target = channel.thread_id or channel.channel_id
        try:
            channel_id = int(target)
        except ValueError as exc:
            raise PlatformError(f"discord channel {target} is not an id") from exc
        found: object = self._client.get_channel(channel_id)
        if found is None:
            try:
                found = await self._client.fetch_channel(channel_id)
            except discord.DiscordException as exc:
                raise PlatformError(f"discord channel {target} is unreachable: {exc}") from exc
        if not isinstance(found, discord.abc.Messageable):
            raise PlatformError(f"discord channel {target} takes no messages")
        return found

    async def _user(self, member: MemberRef) -> discord.abc.Messageable:
        try:
            user_id = int(member.user_id)
        except ValueError as exc:
            raise PlatformError(f"discord member {member.user_id} is not an id") from exc
        try:
            return await self._client.fetch_user(user_id)
        except discord.DiscordException as exc:
            raise PlatformError(f"discord member {member.user_id} is unreachable: {exc}") from exc

    async def _post(
        self,
        target: discord.abc.Messageable,
        *,
        content: str | None,
        embed: discord.Embed | None = None,
        view: discord.ui.View | None = None,
    ) -> None:
        try:
            if embed is not None and view is not None:
                await target.send(embed=embed, view=view)
            else:
                await target.send(content)
        except discord.DiscordException as exc:
            raise PlatformError(f"discord rejected a send: {exc}") from exc


def strip_mention(content: str, me: int) -> str:
    """The message text without the mention that addressed Zipy."""
    text = content
    for token in (f"<@{me}>", f"<@!{me}>"):
        text = text.replace(token, " ")
    return " ".join(text.split())


def roles_of(author: discord.User | discord.Member) -> tuple[str, ...]:
    """The server role names of the sender, empty in a direct message."""
    if not isinstance(author, discord.Member):
        return ()
    return tuple(role.name for role in author.roles)


def attachments(uploaded: Iterable[discord.Attachment]) -> tuple[Attachment, ...]:
    """The images of a message. Anything Discord does not call an image is dropped."""
    found = (Attachment.of(one.url, one.content_type or "") for one in uploaded)
    return tuple(one for one in found if one is not None)
