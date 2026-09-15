"""The discord platform."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar, cast

import discord
from pydantic import BaseModel, ConfigDict, SecretStr

from engine.core.config import Budget
from engine.core.types import (
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
from engine.platforms.discord.render import confirm_embed, confirm_view, parse_custom_id
from engine.telemetry.logging import get

log = get("platforms.discord")


class DiscordSettings(BaseModel):
    """[platforms.discord] settings. Secrets are in .env."""

    model_config = ConfigDict(extra="forbid")

    token: SecretStr = SecretStr("")
    message_limit: int = 2000


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
        """A mention, a direct message, or a reply in a thread Zipy is in."""
        me = self._client.user
        if me is None or message.author.bot or message.author.id == me.id:
            return
        direct = isinstance(message.channel, discord.DMChannel)
        if not direct and not self._addressed(message, me.id):
            return
        workspace = str(message.guild.id) if message.guild else f"dm-{message.author.id}"
        inbound = Inbound(
            channel=channel_ref(workspace, message.channel, str(message.channel.id)),
            member=MemberRef(platform=self.name, user_id=str(message.author.id)),
            display_name=message.author.display_name,
            text=strip_mention(message.content, me.id),
            direct=direct,
            received_at=message.created_at,
            platform_roles=roles_of(message.author),
        )
        await self._to_gateway(self.gateway.message(inbound, self.capabilities))

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

    def _addressed(self, message: discord.Message, me: int) -> bool:
        if any(mentioned.id == me for mentioned in message.mentions):
            return True
        return isinstance(message.channel, discord.Thread) and message.channel.me is not None

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
