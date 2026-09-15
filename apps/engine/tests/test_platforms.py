"""Platform plugins: discovery against zipy.toml, the local round trip, and rendering.

No test opens a connection: the local platform is driven through its line reader and writer, and
the discord and slack platforms are exercised through their pure mapping and rendering functions.
"""

from datetime import UTC, datetime, timedelta

import discord
import pytest

from engine.core.config import PlatformSettings
from engine.core.doubles import MemoryWorkspaces
from engine.core.types import (
    ChannelRef,
    ConfigError,
    OrgId,
    PlatformError,
    Speaker,
    UnknownWorkspace,
    Workspace,
    WorkspaceRef,
)
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
from engine.gateway.render import split
from engine.platforms.discord import platform as discord_platform
from engine.platforms.discord import render as discord_render
from engine.platforms.local.platform import WORKSPACE, LocalPlatform, LocalSettings
from engine.platforms.local.protocol import decode
from engine.platforms.registry import Platforms, check, platform_classes
from engine.platforms.slack import platform as slack_platform
from engine.platforms.slack import render as slack_render

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


class FakeGateway:
    """Records what a platform hands it and returns the outbound it was loaded with."""

    def __init__(self, replies=None, install_replies=None, unknown_until=0):
        self.replies = replies or []
        self.install_replies = install_replies or []
        self.unknown_until = unknown_until
        self.messages: list[Inbound] = []
        self.answers: list[InboundAnswer] = []
        self.installs: list[WorkspaceInstalled] = []
        self.capabilities: list[Capabilities] = []

    async def message(self, event: Inbound, capabilities: Capabilities) -> list[Outbound]:
        self.capabilities.append(capabilities)
        if len(self.messages) < self.unknown_until:
            self.messages.append(event)
            raise UnknownWorkspace("local:local is not linked to an org")
        self.messages.append(event)
        return list(self.replies)

    async def answer(self, event: InboundAnswer, capabilities: Capabilities) -> list[Outbound]:
        self.capabilities.append(capabilities)
        self.answers.append(event)
        return list(self.replies)

    async def installed(self, event: WorkspaceInstalled, budget) -> list[Outbound]:
        self.installs.append(event)
        return list(self.install_replies)


def local(gateway, **settings):
    """A local platform writing into the list it returns beside itself."""
    written: list[str] = []
    platform = LocalPlatform(
        LocalSettings(**settings),
        gateway,
        write_line=written.append,
    )
    return platform, written


def prompt(channel: ChannelRef, confirmation_id: str = "c-1") -> ConfirmPrompt:
    return ConfirmPrompt(
        channel=channel,
        confirmation_id=confirmation_id,
        summary="Move Exec Board to 4pm?",
        expires_at=NOW + timedelta(minutes=2),
    )


# ---------------------------------------------------------------- discovery


def test_every_platform_folder_is_discovered_and_matches_the_committed_config(cfg):
    classes = platform_classes()
    assert sorted(classes) == ["discord", "local", "slack"]
    check(cfg.platforms, classes)


def test_a_platform_folder_without_a_table_fails_at_startup(cfg):
    tables = {name: table for name, table in cfg.platforms.items() if name != "local"}
    with pytest.raises(ConfigError, match="local"):
        check(tables, platform_classes())


def test_a_table_without_a_platform_folder_fails_at_startup(cfg):
    tables = dict(cfg.platforms)
    tables["teams"] = PlatformSettings(enabled=True)
    with pytest.raises(ConfigError, match="teams"):
        check(tables, platform_classes())


def test_an_enabled_table_with_an_unknown_key_fails_at_startup():
    tables = {"local": PlatformSettings(enabled=True, chatty=True)}
    with pytest.raises(ConfigError, match="local"):
        check(tables, {"local": LocalPlatform})


def test_only_enabled_platforms_are_built():
    tables = {"local": PlatformSettings(enabled=False)}
    platforms = Platforms(tables, FakeGateway(), MemoryWorkspaces(), {"local": LocalPlatform})
    assert platforms.enabled == {}
    with pytest.raises(ConfigError, match="local"):
        platforms.get("local")


async def test_a_notice_reaches_the_notice_channel_of_every_enabled_workspace():
    workspaces = MemoryWorkspaces()
    org = OrgId("org-1")
    channel = ChannelRef(workspace=WORKSPACE, channel_id="terminal-0")
    await workspaces.link(Workspace(WORKSPACE, org, "Local dev org", channel))
    await workspaces.link(
        Workspace(WorkspaceRef("discord", "g1"), org, "Robotics", ChannelRef(WORKSPACE, "other"))
    )
    written: list[str] = []
    platforms = Platforms(
        {"local": PlatformSettings(enabled=True)},
        FakeGateway(),
        workspaces,
        {"local": LocalPlatform},
    )
    platforms.enabled["local"]._write_line = written.append
    await platforms.notify(org, "Google connected")
    assert written == ["Google connected"]


# ---------------------------------------------------------------- the local platform


async def test_a_typed_message_round_trips_through_the_gateway():
    channel = ChannelRef(workspace=WORKSPACE, channel_id="terminal-0")
    gateway = FakeGateway(replies=[Text(channel=channel, text="Exec board is Friday at 3pm.")])
    platform, written = local(gateway, member_name="ash")
    await platform.handle("when is exec board?")
    assert written == ["Exec board is Friday at 3pm."]
    inbound = gateway.messages[0]
    assert inbound.text == "when is exec board?"
    assert inbound.channel == channel
    assert inbound.member.platform == "local"
    assert inbound.display_name == "ash"
    assert inbound.direct
    assert [m.speaker for m in await platform.recent(channel, 10)] == [
        Speaker.USER,
        Speaker.ASSISTANT,
    ]


async def test_the_conversation_is_read_back_oldest_first_and_capped_by_limit():
    channel = ChannelRef(workspace=WORKSPACE, channel_id="terminal-0")
    gateway = FakeGateway(replies=[Text(channel=channel, text="ok")])
    platform, _ = local(gateway)
    await platform.handle("one")
    await platform.handle("two")
    recent = await platform.recent(channel, 3)
    assert [m.content for m in recent] == ["ok", "two", "ok"]


async def test_a_new_conversation_starts_a_new_channel_with_no_history():
    channel = ChannelRef(workspace=WORKSPACE, channel_id="terminal-0")
    gateway = FakeGateway(replies=[Text(channel=channel, text="ok")])
    platform, _ = local(gateway)
    await platform.handle("one")
    platform.reset()
    assert platform.channel.channel_id == "terminal-1"
    assert await platform.recent(platform.channel, 10) == []
    with pytest.raises(PlatformError, match="terminal-0"):
        await platform.recent(channel, 10)


async def test_a_reply_is_written_in_the_pieces_the_gateway_split_it_into():
    channel = ChannelRef(workspace=WORKSPACE, channel_id="terminal-0")
    text = "\n".join(f"line {i:03d}" for i in range(40))
    gateway = FakeGateway()
    platform, written = local(gateway, message_limit=100)
    gateway.replies = [
        Text(channel=channel, text=piece)
        for piece in split(text, platform.capabilities.message_limit)
    ]
    await platform.handle("summarize")
    assert len(written) > 1
    assert all(len(line) <= 100 for line in written)
    assert "\n".join(written) == text
    assert gateway.capabilities[0].message_limit == 100


async def test_a_run_reads_lines_until_stdin_closes():
    channel = ChannelRef(workspace=WORKSPACE, channel_id="terminal-0")
    lines = iter(["hello\n", "\n", ""])
    gateway = FakeGateway(replies=[Text(channel=channel, text="hi")])

    async def read_line() -> str:
        return next(lines)

    written: list[str] = []
    platform = LocalPlatform(
        LocalSettings(), gateway, read_line=read_line, write_line=written.append
    )
    await platform.run()
    assert written == ["hi"]
    assert len(gateway.messages) == 1


async def test_an_unlinked_workspace_is_installed_and_the_message_is_asked_again():
    channel = ChannelRef(workspace=WORKSPACE, channel_id="terminal-0")
    gateway = FakeGateway(
        replies=[Text(channel=channel, text="hi")],
        install_replies=[Text(channel=channel, text="Welcome")],
        unknown_until=1,
    )
    platform, written = local(gateway, org_name="Robotics")
    await platform.handle("hello")
    assert [install.name for install in gateway.installs] == ["Robotics"]
    assert written == ["Welcome", "hi"]
    assert len(gateway.messages) == 2


async def test_a_gateway_error_is_written_and_does_not_stop_the_terminal():
    class Failing(FakeGateway):
        async def message(self, event, capabilities):
            raise PlatformError("the model is unreachable")

    platform, written = local(Failing())
    await platform.handle("hello")
    assert written == ["the model is unreachable"]


# ---------------------------------------------------------------- capability degradation


async def test_without_buttons_a_confirmation_is_answered_by_typing():
    channel = ChannelRef(workspace=WORKSPACE, channel_id="terminal-0")
    gateway = FakeGateway(replies=[prompt(channel)])
    platform, written = local(gateway)
    assert platform.capabilities.buttons is False
    await platform.handle("move exec board to 4pm")
    assert written == ["Move Exec Board to 4pm?"]
    await platform.handle("Confirm")
    assert gateway.answers[0].confirmation_id == "c-1"
    assert gateway.answers[0].answer is Answer.CONFIRM


async def test_typed_confirm_is_a_message_again_once_nothing_is_pending():
    channel = ChannelRef(workspace=WORKSPACE, channel_id="terminal-0")
    gateway = FakeGateway(replies=[prompt(channel)])
    platform, _ = local(gateway)
    await platform.handle("move exec board to 4pm")
    gateway.replies = []
    await platform.handle("cancel")
    await platform.handle("cancel")
    assert [event.answer for event in gateway.answers] == [Answer.CANCEL]
    assert [event.text for event in gateway.messages] == ["move exec board to 4pm", "cancel"]


async def test_with_buttons_a_confirmation_carries_its_id_and_answers():
    channel = ChannelRef(workspace=WORKSPACE, channel_id="terminal-0")
    gateway = FakeGateway(replies=[prompt(channel)])
    platform, written = local(gateway, jsonl=True)
    assert platform.capabilities.buttons is True
    await platform.handle('{"op": "ask", "text": "move exec board to 4pm"}')
    result = decode_out(written[0])["result"]
    assert result["confirmation_id"] == "c-1"
    assert result["answers"] == ["confirm", "cancel"]
    await platform.handle('{"op": "confirm", "approve": false}')
    assert gateway.answers[0].answer is Answer.CANCEL


async def test_an_unknown_json_line_is_an_error_line():
    platform, written = local(FakeGateway(), jsonl=True)
    await platform.handle('{"op": "drop_everything"}')
    assert decode_out(written[0])["type"] == "error"
    assert decode(written[0]) is None


async def test_an_answer_with_nothing_pending_says_so():
    platform, written = local(FakeGateway(), jsonl=True)
    await platform.handle('{"op": "confirm", "approve": true}')
    assert "waiting" in decode_out(written[0])["message"]


async def test_the_metrics_snapshot_is_written_only_when_one_is_attached():
    platform, written = local(FakeGateway(), jsonl=True)
    await platform.handle('{"op": "stats"}')
    assert decode_out(written[0])["type"] == "error"
    attached = LocalPlatform(
        LocalSettings(jsonl=True),
        FakeGateway(),
        write_line=written.append,
        stats=lambda: {"zipy_messages": 2.0},
    )
    attached.stats()
    assert decode_out(written[1])["stats"] == {"zipy_messages": 2.0}


async def test_an_outbound_for_another_conversation_is_refused():
    platform, _ = local(FakeGateway())
    elsewhere = ChannelRef(workspace=WorkspaceRef("discord", "g1"), channel_id="c1")
    with pytest.raises(PlatformError, match="c1"):
        await platform.send(Text(channel=elsewhere, text="hi"))


def decode_out(line: str) -> dict:
    import json

    parsed = json.loads(line)
    assert isinstance(parsed, dict)
    return parsed


# ---------------------------------------------------------------- discord


def test_a_discord_button_id_round_trips():
    made = discord_render.custom_id("c-1", Answer.CONFIRM)
    assert discord_render.parse_custom_id(made) == ("c-1", Answer.CONFIRM)
    assert discord_render.parse_custom_id("someone-elses-button") is None
    assert discord_render.parse_custom_id("zipy:confirm:c-1:maybe") is None
    assert discord_render.parse_custom_id("zipy:confirm:confirm") is None


async def test_a_discord_confirmation_renders_an_embed_and_two_buttons():
    pending = prompt(ChannelRef(WorkspaceRef("discord", "g1"), "c1"))
    embed = discord_render.confirm_embed(pending)
    assert embed.description == "Move Exec Board to 4pm?"
    assert embed.footer.text is not None and "expires" in embed.footer.text
    view = discord_render.confirm_view(pending)
    ids = [item.custom_id for item in view.children]
    assert ids == [
        discord_render.custom_id("c-1", Answer.CONFIRM),
        discord_render.custom_id("c-1", Answer.CANCEL),
    ]


def test_a_discord_mention_is_stripped_from_the_text():
    assert discord_platform.strip_mention("<@42> move  exec board", 42) == "move exec board"
    assert discord_platform.strip_mention("<@!42> hello", 42) == "hello"


def test_a_discord_thread_is_its_own_conversation():
    thread = object.__new__(discord.Thread)
    thread.id = 77
    thread.parent_id = 12
    assert discord_platform.channel_ref("g1", thread, "77") == ChannelRef(
        workspace=WorkspaceRef("discord", "g1"), channel_id="12", thread_id="77"
    )
    assert discord_platform.channel_ref("g1", None, "12") == ChannelRef(
        workspace=WorkspaceRef("discord", "g1"), channel_id="12"
    )


def test_discord_roles_are_empty_outside_a_server():
    user = object.__new__(discord.User)
    assert discord_platform.roles_of(user) == ()


async def test_discord_refuses_to_connect_without_a_token():
    platform = discord_platform.DiscordPlatform(
        discord_platform.DiscordSettings(), FakeGateway(), client=FakeClient()
    )
    assert platform.capabilities.buttons is True
    assert platform.capabilities.message_limit == 2000
    with pytest.raises(PlatformError, match="token"):
        await platform.run()


class FakeClient:
    """Enough of discord.Client to register handlers without a connection."""

    def __init__(self):
        self.user = None
        self.handlers = {}

    def event(self, coro):
        self.handlers[coro.__name__] = coro
        return coro


async def test_a_discord_send_to_an_unreachable_channel_is_a_platform_error():
    platform = discord_platform.DiscordPlatform(
        discord_platform.DiscordSettings(), FakeGateway(), client=FakeClient()
    )
    channel = ChannelRef(WorkspaceRef("discord", "g1"), "not-an-id")
    with pytest.raises(PlatformError, match="not-an-id"):
        await platform.send(Text(channel=channel, text="hi"))


# ---------------------------------------------------------------- slack


def test_a_slack_request_is_verified_against_its_signing_secret():
    body = b"payload=1"
    timestamp = str(int(NOW.timestamp()))
    sent = slack_platform.signature("shh", timestamp, body)
    assert slack_platform.verified("shh", timestamp, body, sent, NOW)
    assert not slack_platform.verified("other", timestamp, body, sent, NOW)
    assert not slack_platform.verified("shh", timestamp, b"payload=2", sent, NOW)
    assert not slack_platform.verified("shh", timestamp, body, sent, NOW + timedelta(hours=1))
    assert not slack_platform.verified("shh", "not-a-time", body, sent, NOW)


def test_a_slack_platform_without_a_signing_secret_says_so():
    platform = slack_platform.SlackPlatform(slack_platform.SlackSettings(), FakeGateway())
    with pytest.raises(PlatformError, match="signing secret"):
        platform.verify("1", b"", "v0=x", NOW)


def test_a_slack_mention_becomes_an_inbound_message():
    payload = {
        "type": "event_callback",
        "team_id": "T1",
        "authorizations": [{"user_id": "UBOT"}],
        "event": {
            "type": "app_mention",
            "user": "U1",
            "channel": "C1",
            "text": "<@UBOT> when is exec board?",
            "ts": "1789000000.000100",
        },
    }
    inbound = slack_platform.inbound_from(payload)
    assert inbound is not None
    assert inbound.text == "when is exec board?"
    assert inbound.channel == ChannelRef(WorkspaceRef("slack", "T1"), "C1")
    assert inbound.member.user_id == "U1"
    assert inbound.direct is False


def test_a_slack_thread_reply_keeps_its_thread_and_a_dm_is_direct():
    base = {
        "type": "event_callback",
        "team_id": "T1",
        "event": {
            "type": "message",
            "channel_type": "im",
            "user": "U1",
            "channel": "D1",
            "text": "hello",
            "ts": "1789000000.000300",
            "thread_ts": "1789000000.000100",
        },
    }
    inbound = slack_platform.inbound_from(base)
    assert inbound is not None
    assert inbound.direct is True
    assert inbound.channel.thread_id == "1789000000.000100"


def test_slack_events_zipy_is_not_addressed_in_are_ignored():
    assert slack_platform.inbound_from({"type": "url_verification", "challenge": "c"}) is None
    assert (
        slack_platform.inbound_from(
            {
                "type": "event_callback",
                "team_id": "T1",
                "event": {"type": "message", "user": "U1", "channel": "C1", "ts": "1.0"},
            }
        )
        is None
    )
    assert (
        slack_platform.inbound_from(
            {
                "type": "event_callback",
                "team_id": "T1",
                "event": {
                    "type": "app_mention",
                    "bot_id": "B1",
                    "user": "U1",
                    "channel": "C1",
                    "ts": "1.0",
                },
            }
        )
        is None
    )


def test_a_slack_button_becomes_an_inbound_answer():
    payload = {
        "type": "block_actions",
        "team": {"id": "T1"},
        "channel": {"id": "C1"},
        "user": {"id": "U1"},
        "actions": [
            {
                "action_id": slack_render.CANCEL_ACTION,
                "value": "c-1",
                "action_ts": "1789000000.000100",
            }
        ],
    }
    answer = slack_platform.answer_from(payload)
    assert answer is not None
    assert answer.answer is Answer.CANCEL
    assert answer.confirmation_id == "c-1"
    payload["actions"] = [{"action_id": "someone_elses", "value": "x", "action_ts": "1.0"}]
    assert slack_platform.answer_from(payload) is None


def test_slack_confirmation_blocks_carry_both_answers():
    blocks = slack_render.confirm_blocks(prompt(ChannelRef(WorkspaceRef("slack", "T1"), "C1")))
    assert blocks[0]["text"]["text"] == "Move Exec Board to 4pm?"
    actions = blocks[-1]
    assert actions["block_id"] == "c-1"
    assert [element["action_id"] for element in actions["elements"]] == [
        slack_render.CONFIRM_ACTION,
        slack_render.CANCEL_ACTION,
    ]
    assert all(element["value"] == "c-1" for element in actions["elements"])


async def test_slack_says_what_is_missing_instead_of_half_sending():
    platform = slack_platform.SlackPlatform(slack_platform.SlackSettings(), FakeGateway())
    channel = ChannelRef(WorkspaceRef("slack", "T1"), "C1")
    assert platform.router() is None
    with pytest.raises(PlatformError, match="slack sdk"):
        await platform.send(Text(channel=channel, text="hi"))
    with pytest.raises(PlatformError, match="slack sdk"):
        await platform.recent(channel, 10)
    with pytest.raises(PlatformError, match="slack sdk"):
        await platform.run()
