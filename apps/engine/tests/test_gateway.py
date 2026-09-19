"""Admin command parsing, fitting replies to a platform's limit, and the gateway itself."""

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, SecretStr

from engine.agent.orchestrator import Orchestrator
from engine.agent.prompt import PromptBuilder
from engine.core.config import Agent, Data, Permissions, RateLimit, ToolSettings
from engine.core.doubles import (
    AllowAll,
    FixedEmbedder,
    MemoryAudit,
    MemoryCollaboration,
    MemoryConfirmations,
    MemoryConversation,
    MemoryCredentials,
    MemoryDocuments,
    MemoryOrgContext,
    MemoryOrgs,
    MemoryToolConfig,
    MemoryTrace,
    MemoryWorkspaces,
    NoLimit,
    ScriptedModel,
)
from engine.core.types import (
    ActionType,
    ChannelRef,
    CollaborationState,
    Completion,
    Dimension,
    Evidence,
    FactCategory,
    MemberRef,
    Org,
    OrgFact,
    OrgId,
    OrgToolConfig,
    ProviderAuth,
    RequestContext,
    Role,
    Signal,
    ToolCall,
    Usage,
    Workspace,
)
from engine.core.types.collaboration import apply_signals
from engine.gateway.admin import AdminCommand, Verb, parse
from engine.gateway.gateway import Gateway
from engine.gateway.messages import (
    Answer,
    Capabilities,
    ConfirmPrompt,
    Inbound,
    InboundAnswer,
    Text,
    WorkspaceInstalled,
)
from engine.gateway.render import split
from engine.memory.manager import MemoryManager
from engine.telemetry.metrics import Metrics
from engine.tools.base import Action, BaseTool
from engine.tools.executor import Executor
from engine.tools.registry import Registry

TEMPLATE = (
    Path(__file__).resolve().parents[1] / "agent" / "templates" / "system.md.j2"
).read_text()

DISCORD = Capabilities(
    markup="discord-markdown",
    message_limit=2000,
    buttons=True,
    threads=True,
    direct_messages=True,
)
PLAIN = Capabilities(
    markup="markdown", message_limit=2000, buttons=False, threads=False, direct_messages=False
)


def test_admin_commands_are_parsed_and_requests_are_not():
    assert parse("config calendar reminder 15") == AdminCommand(
        Verb.CONFIG, ("calendar", "reminder", "15")
    )
    assert parse("Status") == AdminCommand(Verb.STATUS, ())
    assert parse("when is the next exec board meeting?") is None


@pytest.mark.parametrize("limit", [2000, 3000])
def test_a_long_reply_is_split_at_newlines_within_the_limit(limit):
    text = "\n".join(f"line {i:04d}" for i in range(800))
    pieces = split(text, limit)
    assert all(len(p) <= limit for p in pieces)
    assert "\n".join(pieces) == text


def test_a_line_longer_than_the_limit_is_cut():
    assert split("x" * 4500, 2000) == ["x" * 2000, "x" * 2000, "x" * 500]


def test_the_local_protocol_accepts_only_known_ops():
    from engine.platforms.local.protocol import decode, encode

    assert decode('{"op": "ask", "text": "status"}') == {"op": "ask", "text": "status"}
    assert decode('{"op": "delete_everything"}') is None
    assert decode("not json") is None
    assert (
        encode("result", result={"answer": "hi"})
        == '{"type": "result", "result": {"answer": "hi"}}'
    )


# ---------------------------------------------------------------- the gateway over doubles


class Settings(BaseModel):
    """The fake tool's only setting."""

    limit: int = 10


class ListParams(BaseModel):
    """Arguments of the read action."""

    day: str


class MoveParams(BaseModel):
    """Arguments of the destructive action."""

    event_id: str
    to: str


class Listed(BaseModel):
    """Result of the read action."""

    events: list[str]


class Moved(BaseModel):
    """Result of the destructive action."""

    event_id: str


class Diary(BaseTool[Settings]):
    """A tool over a provider, with one read and one destructive action."""

    name = "diary"
    provider = "google"
    settings_model = Settings
    actions = {
        "list_events": Action("List the events of a day.", ListParams, Listed),
        "move_event": Action("Move an event.", MoveParams, Moved),
    }

    async def execute(
        self, ctx: RequestContext, action: str, params: BaseModel, auth: ProviderAuth | None
    ) -> BaseModel:
        if action == "list_events":
            return Listed(events=["standup"])
        return Moved(event_id="e1")


@dataclass
class RefuseAll:
    """A rate limiter that refuses every message."""

    seen: list[MemberRef] = field(default_factory=list)

    async def allow(self, org_id: OrgId, member: MemberRef) -> bool:
        self.seen.append(member)
        return False


@dataclass
class Stack:
    """Everything one gateway is built from, so a test can read what it wrote."""

    gateway: Gateway
    model: ScriptedModel
    orgs: MemoryOrgs
    workspaces: MemoryWorkspaces
    org_context: MemoryOrgContext
    credentials: MemoryCredentials
    tool_config: MemoryToolConfig
    confirmations: MemoryConfirmations
    collaboration: MemoryCollaboration
    metrics: Metrics


def tables() -> dict[str, ToolSettings]:
    """The [tools.*] table matching the fake tool."""
    return {
        "diary": ToolSettings(
            provider="google",
            actions={
                "list_events": ActionType.READ,
                "move_event": ActionType.DESTRUCTIVE,
            },
        )
    }


def stack(
    cfg: Any,
    ctx: Any,
    script: list[Completion] | None = None,
    *,
    limiter: Any = None,
    linked: bool = True,
    budget_cents: int = 1000,
    spent_cents: int = 0,
    connected: bool = True,
) -> Stack:
    """A gateway over in-memory doubles, with the model scripted."""
    orgs = MemoryOrgs()
    orgs.orgs[ctx.org_id] = Org(ctx.org_id, "Robotics Club", True, budget_cents, spent_cents)
    orgs.roles[(ctx.org_id, ctx.member)] = ctx.role
    workspaces = MemoryWorkspaces()
    if linked:
        workspaces.links[ctx.channel.workspace] = Workspace(
            ref=ctx.channel.workspace,
            org_id=ctx.org_id,
            name="Robotics Club",
            notice_channel=ctx.channel,
        )
    credentials = MemoryCredentials()
    if connected:
        credentials.auths[(ctx.org_id, "google")] = ProviderAuth(
            org_id=ctx.org_id,
            provider="google",
            access_token=SecretStr("tok-secret-value"),
            scopes=("calendar",),
            expires_at=None,
        )
    org_context = MemoryOrgContext()
    tool_config = MemoryToolConfig()
    confirmations = MemoryConfirmations()
    collaboration = MemoryCollaboration()
    registry = Registry(tables(), {"diary": Diary})
    model = ScriptedModel(script=list(script or []))
    orchestrator = Orchestrator(
        agent=Agent(),
        model=model,
        memory=MemoryManager(
            memory=cfg.memory,
            conversation=MemoryConversation(),
            org_context=org_context,
            embedder=FixedEmbedder([0.1]),
            documents=MemoryDocuments(),
            collaboration=collaboration,
            settings=cfg.collaboration,
        ),
        prompts=PromptBuilder(TEMPLATE, "Zipy"),
        registry=registry,
        executor=Executor(
            registry=registry,
            permissions=Permissions(),
            credentials=credentials,
            tool_config=tool_config,
            audit=MemoryAudit(),
            trace=MemoryTrace(),
            limiter=NoLimit(),
            limits=RateLimit(),
        ),
        orgs=orgs,
        credentials=credentials,
        tool_config=tool_config,
        confirmations=confirmations,
        trace=MemoryTrace(),
    )
    metrics = Metrics()
    return Stack(
        gateway=Gateway(
            config=cfg,
            orchestrator=orchestrator,
            registry=registry,
            orgs=orgs,
            workspaces=workspaces,
            org_context=org_context,
            credentials=credentials,
            tool_config=tool_config,
            rate_limiter=limiter if limiter is not None else AllowAll(),
            collaboration=collaboration,
            metrics=metrics,
        ),
        model=model,
        orgs=orgs,
        workspaces=workspaces,
        org_context=org_context,
        credentials=credentials,
        tool_config=tool_config,
        confirmations=confirmations,
        collaboration=collaboration,
        metrics=metrics,
    )


def inbound(ctx: Any, text: str) -> Inbound:
    """One message from the member of the context."""
    return Inbound(
        channel=ctx.channel,
        member=ctx.member,
        display_name=ctx.display_name,
        text=text,
        direct=False,
        received_at=ctx.received_at,
    )


def call(name: str, **arguments: Any) -> ToolCall:
    """One tool call from the model."""
    return ToolCall(id=f"c-{name}", name=name, arguments=arguments)


def body(replies: list[Any]) -> str:
    """Every Text of a reply, joined as it is posted."""
    return "\n".join(r.text for r in replies if isinstance(r, Text))


def admin(ctx: Any) -> Any:
    """The same context under the admin role."""
    return replace(ctx, role=Role.ADMIN)


async def test_an_unlinked_workspace_gets_setup_instructions_not_an_error(cfg, ctx):
    unit = stack(cfg, ctx, linked=False)
    replies = await unit.gateway.message(inbound(ctx, "when do we meet?"), DISCORD)
    assert all(isinstance(r, Text) for r in replies)
    assert "not linked" in body(replies) and "setup" in body(replies)
    assert unit.model.requests == [], "no model call for a workspace with no org"


async def test_a_rate_limited_member_is_refused_before_the_model(cfg, ctx):
    limiter = RefuseAll()
    unit = stack(cfg, ctx, [Completion(text="never reached")], limiter=limiter)
    replies = await unit.gateway.message(inbound(ctx, "when do we meet?"), DISCORD)
    assert "more than 10 messages" in body(replies)
    assert unit.model.requests == [], "the limit is checked before the model"
    assert limiter.seen == [ctx.member]
    assert (
        unit.metrics.snapshot()["zipy_messages_total{outcome=rate_limited,platform=discord}"] == 1
    )


async def test_an_admin_command_is_answered_without_the_model(cfg, ctx):
    unit = stack(cfg, ctx)
    replies = await unit.gateway.message(inbound(ctx, "status"), DISCORD)
    text = body(replies)
    assert "Robotics Club" in text
    assert "google" in text and "diary" in text
    assert "0 of 1000 cents" in text
    assert unit.model.requests == [], "status never calls the model"


async def test_a_reply_longer_than_the_platform_limit_is_split(cfg, ctx):
    answer = "\n".join(f"line {i:04d}" for i in range(400))
    unit = stack(cfg, ctx, [Completion(text=answer, usage=Usage(1, 1, 0.5))])
    small = replace(DISCORD, message_limit=200)
    replies = await unit.gateway.message(inbound(ctx, "list every line"), small)
    assert len(replies) > 1
    assert all(isinstance(r, Text) and len(r.text) <= 200 for r in replies)
    assert body(replies) == answer


async def test_a_destructive_call_comes_back_as_a_confirm_prompt(cfg, ctx):
    unit = stack(
        cfg,
        ctx,
        [Completion(text="", tool_calls=(call("diary.move_event", event_id="e1", to="4pm"),))],
    )
    replies = await unit.gateway.message(inbound(ctx, "move standup to 4pm"), DISCORD)
    assert len(replies) == 1
    prompt = replies[0]
    assert isinstance(prompt, ConfirmPrompt)
    assert "move_event" in prompt.summary
    assert prompt.confirmation_id in unit.confirmations.pending


async def test_a_platform_without_buttons_is_told_the_typed_answers(cfg, ctx):
    unit = stack(
        cfg,
        ctx,
        [Completion(text="", tool_calls=(call("diary.move_event", event_id="e1", to="4pm"),))],
    )
    replies = await unit.gateway.message(inbound(ctx, "move standup to 4pm"), PLAIN)
    assert isinstance(replies[0], ConfirmPrompt)
    assert body(replies) == f"Reply {Answer.CONFIRM.value} or {Answer.CANCEL.value}."


async def test_confirming_runs_the_call_and_cancelling_changes_nothing(cfg, ctx):
    unit = stack(
        cfg,
        ctx,
        [
            Completion(text="", tool_calls=(call("diary.move_event", event_id="e1", to="4pm"),)),
            Completion(text="Moved standup to 4pm."),
        ],
    )
    asked = await unit.gateway.message(inbound(ctx, "move standup to 4pm"), DISCORD)
    prompt = asked[0]
    assert isinstance(prompt, ConfirmPrompt)
    replies = await unit.gateway.answer(
        InboundAnswer(
            channel=ctx.channel,
            member=ctx.member,
            confirmation_id=prompt.confirmation_id,
            answer=Answer.CONFIRM,
            received_at=ctx.received_at,
        ),
        DISCORD,
    )
    assert body(replies) == "Moved standup to 4pm."
    assert prompt.confirmation_id not in unit.confirmations.pending


async def test_cancelling_drops_the_call_without_running_it(cfg, ctx):
    unit = stack(
        cfg,
        ctx,
        [Completion(text="", tool_calls=(call("diary.move_event", event_id="e1", to="4pm"),))],
    )
    asked = await unit.gateway.message(inbound(ctx, "move standup to 4pm"), DISCORD)
    prompt = asked[0]
    assert isinstance(prompt, ConfirmPrompt)
    replies = await unit.gateway.answer(
        InboundAnswer(
            channel=ctx.channel,
            member=ctx.member,
            confirmation_id=prompt.confirmation_id,
            answer=Answer.CANCEL,
            received_at=ctx.received_at,
        ),
        DISCORD,
    )
    assert "Cancelled" in body(replies)
    assert unit.confirmations.pending == {}
    assert len(unit.model.requests) == 1, "cancelling never returns to the model"


async def test_an_expired_confirmation_says_so_instead_of_running(cfg, ctx):
    unit = stack(
        cfg,
        ctx,
        [Completion(text="", tool_calls=(call("diary.move_event", event_id="e1", to="4pm"),))],
    )
    asked = await unit.gateway.message(inbound(ctx, "move standup to 4pm"), DISCORD)
    prompt = asked[0]
    assert isinstance(prompt, ConfirmPrompt)
    late = datetime(2026, 9, 14, tzinfo=UTC)
    replies = await unit.gateway.answer(
        InboundAnswer(
            channel=ctx.channel,
            member=ctx.member,
            confirmation_id=prompt.confirmation_id,
            answer=Answer.CONFIRM,
            received_at=late,
        ),
        DISCORD,
    )
    assert "unknown or expired" in body(replies)


async def test_an_org_over_its_budget_is_told_rather_than_called(cfg, ctx):
    unit = stack(cfg, ctx, [Completion(text="never reached")], budget_cents=10, spent_cents=10)
    replies = await unit.gateway.message(inbound(ctx, "when do we meet?"), DISCORD)
    assert "budget" in body(replies)
    assert unit.model.requests == []


async def test_only_an_admin_changes_the_org(cfg, ctx):
    unit = stack(cfg, ctx)
    replies = await unit.gateway.message(inbound(ctx, "disable diary"), DISCORD)
    assert body(replies) == "Only an admin may run disable."
    assert unit.tool_config.by_org == {}


async def test_an_admin_enables_and_disables_a_tool_for_the_org(cfg, ctx):
    unit = stack(cfg, admin(ctx))
    await unit.gateway.message(inbound(admin(ctx), "disable diary"), DISCORD)
    assert unit.tool_config.by_org[ctx.org_id]["diary"] == OrgToolConfig("diary", False, {})
    replies = await unit.gateway.message(inbound(admin(ctx), "enable diary"), DISCORD)
    assert unit.tool_config.by_org[ctx.org_id]["diary"].enabled is True
    assert "enabled" in body(replies)


async def test_an_unknown_tool_says_which_tools_exist(cfg, ctx):
    unit = stack(cfg, admin(ctx))
    replies = await unit.gateway.message(inbound(admin(ctx), "enable trello"), DISCORD)
    assert "diary" in body(replies) and "trello" in body(replies)
    assert unit.tool_config.by_org == {}


async def test_a_per_org_setting_is_validated_before_it_is_stored(cfg, ctx):
    unit = stack(cfg, admin(ctx))
    replies = await unit.gateway.message(inbound(admin(ctx), "config diary limit 25"), DISCORD)
    assert "25" in body(replies)
    assert unit.tool_config.by_org[ctx.org_id]["diary"].overrides == {"limit": 25}
    refused = await unit.gateway.message(inbound(admin(ctx), "config diary limit soon"), DISCORD)
    assert "invalid" in body(refused)
    assert unit.tool_config.by_org[ctx.org_id]["diary"].overrides == {"limit": 25}


async def test_facts_are_remembered_and_forgotten(cfg, ctx):
    unit = stack(cfg, admin(ctx))
    await unit.gateway.message(
        inbound(admin(ctx), "remember tool_mapping budget sheet: the Finance folder"), DISCORD
    )
    assert unit.org_context.by_org[ctx.org_id]["budget sheet"] == OrgFact(
        FactCategory.TOOL_MAPPING, "budget sheet", "the Finance folder"
    )
    replies = await unit.gateway.message(inbound(admin(ctx), "forget budget sheet"), DISCORD)
    assert "Forgotten" in body(replies)
    assert unit.org_context.by_org[ctx.org_id] == {}
    missing = await unit.gateway.message(inbound(admin(ctx), "forget nothing"), DISCORD)
    assert "no fact called nothing" in body(missing)


async def test_a_fact_without_a_key_and_value_is_refused_with_the_format(cfg, ctx):
    unit = stack(cfg, admin(ctx))
    replies = await unit.gateway.message(inbound(admin(ctx), "remember exec board"), DISCORD)
    assert "remember <key>: <value>" in body(replies)
    assert unit.org_context.by_org == {}


async def test_connect_answers_privately_with_a_signed_link(cfg, ctx, monkeypatch):
    monkeypatch.setattr(
        "engine.gateway.gateway.sign", lambda state, key: f"signed-{state.provider}"
    )
    keyed = cfg.model_copy(update={"data": Data(fernet_key=SecretStr("a-key"))})
    unit = stack(keyed, admin(ctx))
    replies = await unit.gateway.message(inbound(admin(ctx), "connect google"), DISCORD)
    assert all(isinstance(r, Text) and r.private_to == ctx.member for r in replies)
    assert "/auth/google?state=signed-google" in body(replies)


async def test_connect_without_a_signing_key_says_what_is_missing(cfg, ctx):
    unit = stack(cfg, admin(ctx))
    replies = await unit.gateway.message(inbound(admin(ctx), "connect google"), DISCORD)
    assert "data.fernet_key is not set" in body(replies)


async def test_a_platform_without_direct_messages_says_so_before_a_private_answer(cfg, ctx):
    unit = stack(cfg, admin(ctx))
    replies = await unit.gateway.message(inbound(admin(ctx), "setup"), PLAIN)
    assert all(isinstance(r, Text) and r.private_to is None for r in replies)
    assert "no direct messages" in body(replies)
    assert "connect google" in body(replies)


async def test_installing_creates_the_org_links_the_workspace_and_makes_an_admin(cfg, ctx):
    unit = stack(cfg, ctx, linked=False)
    installer = MemberRef("discord", "u9")
    replies = await unit.gateway.installed(
        WorkspaceInstalled(channel=ctx.channel, installed_by=installer, name="Robotics Club"),
        cfg.budget,
    )
    linked = unit.workspaces.links[ctx.channel.workspace]
    assert linked.name == "Robotics Club"
    assert unit.orgs.orgs[linked.org_id].budget_cents == cfg.budget.monthly_cents
    assert unit.orgs.roles[(linked.org_id, installer)] is Role.ADMIN
    assert "setup" in body(replies)


async def test_installing_a_linked_workspace_twice_changes_nothing(cfg, ctx):
    unit = stack(cfg, ctx)
    before = dict(unit.orgs.orgs)
    replies = await unit.gateway.installed(
        WorkspaceInstalled(
            channel=ctx.channel, installed_by=MemberRef("discord", "u9"), name="Other"
        ),
        cfg.budget,
    )
    assert "already linked" in body(replies)
    assert unit.orgs.orgs == before
    assert unit.workspaces.links[ctx.channel.workspace].name == "Robotics Club"


async def test_a_thread_is_its_own_conversation_and_carries_the_same_org(cfg, ctx):
    unit = stack(cfg, ctx, [Completion(text="Friday.")])
    thread = ChannelRef(ctx.channel.workspace, ctx.channel.channel_id, "t7")
    event = replace(inbound(ctx, "when do we meet?"), channel=thread)
    replies = await unit.gateway.message(event, DISCORD)
    assert [r.channel for r in replies] == [thread]
    assert body(replies) == "Friday."


async def test_metrics_count_messages_by_platform_and_outcome_never_by_org(cfg, ctx):
    unit = stack(cfg, ctx, [Completion(text="Friday.")])
    await unit.gateway.message(inbound(ctx, "when do we meet?"), DISCORD)
    snapshot = unit.metrics.snapshot()
    assert snapshot["zipy_messages_total{outcome=reply,platform=discord}"] == 1
    assert not any(str(ctx.org_id) in key for key in snapshot)


def _on(cfg: Any) -> Any:
    """The same config with collaboration switched on and one observation enough to show."""
    switched = cfg.collaboration.model_copy(update={"enabled": True, "min_observations": 1})
    return cfg.model_copy(update={"collaboration": switched})


async def test_prefer_is_the_one_command_a_member_runs_without_being_an_admin(cfg, ctx):
    unit = stack(_on(cfg), ctx)
    replies = await unit.gateway.message(inbound(ctx, "prefer less depth"), DISCORD)
    assert "admin" not in body(replies)
    assert unit.collaboration.by_member[(ctx.org_id, ctx.member)].score(Dimension.DEPTH) < 0.5


async def test_prefer_writes_only_the_caller_and_never_another_member(cfg, ctx):
    unit = stack(_on(cfg), ctx)
    await unit.gateway.message(inbound(ctx, "prefer more autonomy"), DISCORD)
    assert list(unit.collaboration.by_member) == [(ctx.org_id, ctx.member)]


async def test_a_stated_preference_outweighs_one_observation(cfg, ctx):
    unit = stack(_on(cfg), ctx)
    await unit.gateway.message(inbound(ctx, "prefer less depth"), DISCORD)
    stated = unit.collaboration.by_member[(ctx.org_id, ctx.member)].score(Dimension.DEPTH)
    observed = apply_signals(
        CollaborationState(member=ctx.member),
        [Signal(Dimension.DEPTH, 0.0, Evidence.CONFIRMATION_CANCELLED)],
    ).score(Dimension.DEPTH)
    assert stated < observed


async def test_prefer_shows_what_was_read_and_forget_drops_it(cfg, ctx):
    unit = stack(_on(cfg), ctx)
    await unit.gateway.message(inbound(ctx, "prefer less depth"), DISCORD)
    shown = body(await unit.gateway.message(inbound(ctx, "prefer"), DISCORD))
    assert "Answer briefly" in shown
    await unit.gateway.message(inbound(ctx, "prefer forget"), DISCORD)
    assert unit.collaboration.by_member == {}


async def test_a_preference_that_names_nothing_real_is_refused_with_the_format(cfg, ctx):
    unit = stack(_on(cfg), ctx)
    replies = await unit.gateway.message(inbound(ctx, "prefer louder"), DISCORD)
    assert "prefer more <dimension>" in body(replies)
    assert unit.collaboration.by_member == {}


async def test_prefer_says_the_feature_is_off_rather_than_pretending_to_store(cfg, ctx):
    unit = stack(cfg, ctx)
    replies = await unit.gateway.message(inbound(ctx, "prefer less depth"), DISCORD)
    assert "off in this deployment" in body(replies)
    assert unit.collaboration.by_member == {}


async def test_status_says_nothing_about_a_person_while_collaboration_is_off(cfg, ctx):
    unit = stack(cfg, ctx)
    assert "how you work" not in body(await unit.gateway.message(inbound(ctx, "status"), DISCORD))


async def _answer(unit: Stack, ctx: Any, answer: Answer) -> None:
    """Ask for a destructive call, then answer the confirmation it comes back with."""
    asked = await unit.gateway.message(inbound(ctx, "move standup to 4pm"), DISCORD)
    prompt = asked[0]
    assert isinstance(prompt, ConfirmPrompt)
    await unit.gateway.answer(
        InboundAnswer(
            channel=ctx.channel,
            member=ctx.member,
            confirmation_id=prompt.confirmation_id,
            answer=answer,
            received_at=ctx.received_at,
        ),
        DISCORD,
    )


def _script() -> list[Completion]:
    """A destructive call and the reply that follows it."""
    return [
        Completion(text="", tool_calls=(call("diary.move_event", event_id="e1", to="4pm"),)),
        Completion(text="Moved standup to 4pm."),
    ]


async def test_confirming_reads_as_wanting_to_be_asked_less(cfg, ctx):
    unit = stack(_on(cfg), ctx, _script())
    await _answer(unit, ctx, Answer.CONFIRM)
    assert unit.collaboration.by_member[(ctx.org_id, ctx.member)].score(Dimension.AUTONOMY) > 0.5


async def test_cancelling_reads_as_wanting_to_be_asked_more(cfg, ctx):
    unit = stack(_on(cfg), ctx, _script())
    await _answer(unit, ctx, Answer.CANCEL)
    assert unit.collaboration.by_member[(ctx.org_id, ctx.member)].score(Dimension.AUTONOMY) < 0.5


async def test_an_answered_confirmation_is_observed_only_while_collaboration_is_on(cfg, ctx):
    unit = stack(cfg, ctx, _script())
    await _answer(unit, ctx, Answer.CONFIRM)
    assert unit.collaboration.by_member == {}
