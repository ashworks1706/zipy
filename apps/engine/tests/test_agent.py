"""The agent core: the executor's checks and audit, and the tool-calling loop."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, SecretStr

from engine.agent.orchestrator import Orchestrator
from engine.agent.prompt import RECALL_HEADER, PromptBuilder
from engine.core.config import Agent, Permissions, ToolSettings
from engine.core.doubles import (
    FixedEmbedder,
    MemoryAudit,
    MemoryConfirmations,
    MemoryConversation,
    MemoryCredentials,
    MemoryDocuments,
    MemoryOrgContext,
    MemoryOrgs,
    MemoryToolConfig,
    MemoryTrace,
    ScriptedModel,
)
from engine.core.types import (
    ActionType,
    AgentReply,
    BudgetExceeded,
    Chunk,
    Completion,
    ConfirmationError,
    NeedsConfirmation,
    Org,
    OrgId,
    ProviderAuth,
    Role,
    Speaker,
    ToolCall,
    ToolError,
    Usage,
)
from engine.memory.manager import Context, MemoryManager
from engine.tools.base import Action, BaseTool
from engine.tools.executor import Executor
from engine.tools.registry import Registry

TEMPLATE = (
    Path(__file__).resolve().parents[1] / "agent" / "templates" / "system.md.j2"
).read_text()


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

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.calls: list[tuple[str, BaseModel]] = []

    async def execute(self, action: str, params: BaseModel, auth: ProviderAuth | None) -> BaseModel:
        if auth is None:
            raise ToolError("no credential reached the tool")
        self.calls.append((action, params))
        if action == "list_events":
            return Listed(events=["standup", "retro"])
        return Moved(event_id="e1")

    def target(self, action: str, params: BaseModel) -> str:
        return getattr(params, "event_id", "")


class Breaks(Diary):
    """A tool whose action always fails."""

    name = "breaks"

    async def execute(self, action: str, params: BaseModel, auth: ProviderAuth | None) -> BaseModel:
        raise ToolError("the provider said no")


def tables() -> dict[str, ToolSettings]:
    """The [tools.*] tables matching the fake tools."""
    actions = {"list_events": ActionType.READ, "move_event": ActionType.DESTRUCTIVE}
    return {
        "diary": ToolSettings(provider="google", actions=actions),
        "breaks": ToolSettings(provider="google", actions=actions),
    }


def registry() -> Registry:
    """A registry over the fake tools."""
    return Registry(tables(), {"diary": Diary, "breaks": Breaks})


def connected(org_id: OrgId) -> MemoryCredentials:
    """A credential store with google connected for the org."""
    store = MemoryCredentials()
    store.auths[(org_id, "google")] = ProviderAuth(
        org_id=org_id,
        provider="google",
        access_token=SecretStr("tok-secret-value"),
        scopes=("calendar",),
        expires_at=None,
    )
    return store


def executor(
    ctx: Any, credentials: MemoryCredentials | None = None, audit: MemoryAudit | None = None
) -> tuple[Executor, MemoryAudit]:
    """An executor over the fake registry, and the audit log it writes to."""
    log = audit or MemoryAudit()
    return (
        Executor(
            registry=registry(),
            permissions=Permissions(),
            credentials=credentials if credentials is not None else connected(ctx.org_id),
            tool_config=MemoryToolConfig(),
            audit=log,
            trace=MemoryTrace(),
        ),
        log,
    )


def call(name: str, **arguments: Any) -> ToolCall:
    """One tool call from the model."""
    return ToolCall(id=f"c-{name}", name=name, arguments=arguments)


# ---------------------------------------------------------------- the executor


async def test_a_read_runs_and_is_audited(ctx):
    run, audit = executor(ctx)
    outcome = await run.run(ctx, call("diary.list_events", day="friday"))
    assert outcome.ok
    assert "standup" in outcome.content
    assert [(e.action, e.ok, e.payload) for e in audit.entries] == [
        ("diary.list_events", True, {"day": "friday"})
    ]


async def test_a_member_may_not_run_a_destructive_action(ctx):
    run, audit = executor(ctx)
    outcome = await run.run(
        replace_role(ctx, Role.MEMBER), call("diary.move_event", event_id="e1", to="4pm")
    )
    assert not outcome.ok
    assert "PermissionDenied" in outcome.content
    assert audit.entries[0].ok is False, "a refused call is still audited"


async def test_bad_arguments_come_back_as_something_the_model_can_fix(ctx):
    run, _ = executor(ctx)
    outcome = await run.run(ctx, call("diary.list_events", weekday="friday"))
    assert not outcome.ok
    assert "arguments are invalid" in outcome.content


async def test_a_tool_failure_is_a_failed_outcome_not_an_exception(ctx):
    run, audit = executor(ctx)
    outcome = await run.run(ctx, call("breaks.list_events", day="friday"))
    assert not outcome.ok
    assert "the provider said no" in outcome.content
    assert audit.entries[0].error.startswith("ToolError")


async def test_a_credential_never_reaches_the_model_or_the_audit_log(ctx):
    run, audit = executor(ctx)
    outcome = await run.run(ctx, call("diary.move_event", event_id="e1", to="4pm"))
    assert outcome.ok
    assert "tok-secret-value" not in outcome.content
    assert "tok-secret-value" not in repr(audit.entries)


async def test_a_tool_whose_provider_is_not_connected_says_so(ctx):
    run, _ = executor(ctx, credentials=MemoryCredentials())
    outcome = await run.run(ctx, call("diary.list_events", day="friday"))
    assert not outcome.ok
    assert "no credential" in outcome.content


async def test_the_audit_names_what_the_action_acted_on(ctx):
    run, audit = executor(ctx)
    await run.run(ctx, call("diary.move_event", event_id="e7", to="4pm"))
    assert audit.entries[0].target == "e7"


# ---------------------------------------------------------------- the loop


def replace_role(ctx: Any, role: Role) -> Any:
    """The same context under another role."""
    from dataclasses import replace

    return replace(ctx, role=role)


def orchestrator(
    ctx: Any,
    cfg: Any,
    script: list[Completion],
    *,
    budget_cents: int = 1000,
    spent_cents: int = 0,
    max_iterations: int = 8,
    confirmations: MemoryConfirmations | None = None,
    audit: MemoryAudit | None = None,
) -> tuple[Orchestrator, ScriptedModel, MemoryOrgs, MemoryConfirmations]:
    """An orchestrator over doubles, with the model scripted."""
    orgs = MemoryOrgs()
    orgs.orgs[ctx.org_id] = Org(ctx.org_id, "Robotics Club", True, budget_cents, spent_cents)
    org_context = MemoryOrgContext()
    memory = MemoryManager(
        memory=cfg.memory,
        conversation=MemoryConversation(),
        org_context=org_context,
        embedder=FixedEmbedder([0.1]),
        documents=MemoryDocuments(),
    )
    model = ScriptedModel(script=script)
    held = confirmations if confirmations is not None else MemoryConfirmations()
    run, _ = executor(ctx, audit=audit)
    agent = Orchestrator(
        agent=Agent(max_iterations=max_iterations),
        model=model,
        memory=memory,
        prompts=PromptBuilder(TEMPLATE, "Zipy"),
        registry=registry(),
        executor=run,
        orgs=orgs,
        credentials=connected(ctx.org_id),
        tool_config=MemoryToolConfig(),
        confirmations=held,
        trace=MemoryTrace(),
    )
    return agent, model, orgs, held


async def test_a_message_the_model_answers_needs_no_tools(ctx, cfg):
    agent, model, orgs, _ = orchestrator(
        ctx, cfg, [Completion(text="We meet Fridays.", usage=Usage(10, 5, 2.0))]
    )
    result = await agent.handle(ctx, "when do we meet?", "discord-markdown")
    assert isinstance(result, AgentReply)
    assert result.text == "We meet Fridays."
    assert result.usage.cost_cents == 2.0
    assert orgs.orgs[ctx.org_id].spent_cents == 2, "the call is charged to the org"
    assert len(model.requests) == 1


async def test_a_read_call_runs_and_its_result_goes_back_to_the_model(ctx, cfg):
    agent, model, _, _ = orchestrator(
        ctx,
        cfg,
        [
            Completion(text="", tool_calls=(call("diary.list_events", day="friday"),)),
            Completion(text="Standup and retro."),
        ],
    )
    result = await agent.handle(ctx, "what is on friday?", "discord-markdown")
    assert isinstance(result, AgentReply)
    assert result.text == "Standup and retro."
    second = model.requests[1]
    assert second[-1].speaker is Speaker.TOOL
    assert "standup" in second[-1].content
    assert second[-2].speaker is Speaker.ASSISTANT, "the tool result follows the turn that asked"


async def test_a_destructive_call_stops_the_loop_and_waits(ctx, cfg):
    agent, _, _, held = orchestrator(
        ctx,
        cfg,
        [Completion(text="", tool_calls=(call("diary.move_event", event_id="e1", to="4pm"),))],
    )
    result = await agent.handle(ctx, "move standup to 4pm", "discord-markdown")
    assert isinstance(result, NeedsConfirmation)
    pending = result.pending
    assert pending.call.name == "diary.move_event"
    assert "event_id='e1'" in pending.summary
    assert pending.expires_at == ctx.received_at + timedelta(seconds=120)
    assert held.pending[pending.id] is pending, "it is stored for the gateway to resume"


async def test_reads_before_a_destructive_call_still_run(ctx, cfg):
    diary_registry = registry()
    agent, _, _, _ = orchestrator(
        ctx,
        cfg,
        [
            Completion(
                text="",
                tool_calls=(
                    call("diary.list_events", day="friday"),
                    call("diary.move_event", event_id="e1", to="4pm"),
                ),
            )
        ],
    )
    assert diary_registry.action_type("diary.move_event") is ActionType.DESTRUCTIVE
    result = await agent.handle(ctx, "move standup", "discord-markdown")
    assert isinstance(result, NeedsConfirmation)
    assert result.pending.call.name == "diary.move_event"


async def test_confirming_runs_the_call_and_carries_on(ctx, cfg):
    held = MemoryConfirmations()
    audit = MemoryAudit()
    agent, model, _, _ = orchestrator(
        ctx,
        cfg,
        [
            Completion(text="", tool_calls=(call("diary.move_event", event_id="e1", to="4pm"),)),
            Completion(text="Moved standup to 4pm."),
        ],
        confirmations=held,
        audit=audit,
    )
    asked = await agent.handle(ctx, "move standup to 4pm", "discord-markdown")
    assert isinstance(asked, NeedsConfirmation)
    result = await agent.confirm(ctx, asked.pending.id, "discord-markdown")
    assert isinstance(result, AgentReply)
    assert result.text == "Moved standup to 4pm."
    assert [e.action for e in audit.entries] == ["diary.move_event"]
    assert model.requests[1][-1].speaker is Speaker.TOOL, "the loop resumes from the result"


async def test_an_unknown_confirmation_is_refused(ctx, cfg):
    agent, _, _, _ = orchestrator(ctx, cfg, [])
    with pytest.raises(ConfirmationError, match="unknown or expired"):
        await agent.confirm(ctx, "nope", "discord-markdown")


async def test_a_confirmation_that_expired_is_refused(ctx, cfg):
    from dataclasses import replace

    agent, _, _, _ = orchestrator(
        ctx,
        cfg,
        [Completion(text="", tool_calls=(call("diary.move_event", event_id="e1", to="4pm"),))],
    )
    asked = await agent.handle(ctx, "move standup", "discord-markdown")
    assert isinstance(asked, NeedsConfirmation)
    late = replace(ctx, received_at=asked.pending.expires_at + timedelta(seconds=1))
    with pytest.raises(ConfirmationError, match="unknown or expired"):
        await agent.confirm(late, asked.pending.id, "discord-markdown")


async def test_a_confirmation_from_another_org_is_refused(ctx, cfg):
    from dataclasses import replace

    agent, _, _, held = orchestrator(
        ctx,
        cfg,
        [Completion(text="", tool_calls=(call("diary.move_event", event_id="e1", to="4pm"),))],
    )
    asked = await agent.handle(ctx, "move standup", "discord-markdown")
    assert isinstance(asked, NeedsConfirmation)
    intruder = replace(ctx, org_id=OrgId("org-2"))
    with pytest.raises(ConfirmationError, match="another org"):
        await agent.confirm(intruder, asked.pending.id, "discord-markdown")


async def test_cancelling_drops_the_call(ctx, cfg):
    agent, _, _, held = orchestrator(
        ctx,
        cfg,
        [Completion(text="", tool_calls=(call("diary.move_event", event_id="e1", to="4pm"),))],
    )
    asked = await agent.handle(ctx, "move standup", "discord-markdown")
    assert isinstance(asked, NeedsConfirmation)
    await agent.cancel(ctx, asked.pending.id)
    assert held.pending == {}


async def test_running_out_of_turns_says_what_it_did(ctx, cfg):
    reading = Completion(text="", tool_calls=(call("diary.list_events", day="friday"),))
    agent, _, _, _ = orchestrator(ctx, cfg, [reading, reading], max_iterations=2)
    result = await agent.handle(ctx, "what is on friday?", "discord-markdown")
    assert isinstance(result, AgentReply)
    assert "stopped after 2 turns" in result.text
    assert "diary.list_events" in result.text, "it names what it ran"


async def test_an_org_at_its_budget_gets_no_model_call(ctx, cfg):
    agent, model, _, _ = orchestrator(ctx, cfg, [], budget_cents=100, spent_cents=100)
    with pytest.raises(BudgetExceeded, match="Robotics Club"):
        await agent.handle(ctx, "hello", "discord-markdown")
    assert model.requests == [], "the budget is checked before the call"


async def test_the_budget_stops_the_loop_partway(ctx, cfg):
    reading = Completion(
        text="", tool_calls=(call("diary.list_events", day="friday"),), usage=Usage(0, 0, 60.0)
    )
    agent, model, _, _ = orchestrator(ctx, cfg, [reading, reading], budget_cents=100)
    with pytest.raises(BudgetExceeded):
        await agent.handle(ctx, "what is on friday?", "discord-markdown")
    assert len(model.requests) == 2, "two calls fit the budget, the third does not"


# ---------------------------------------------------------------- the prompt


def build(context: Context, message: str = "hi", outcomes=()) -> list[Any]:
    """The message array for one request."""
    from engine.core.types import ChannelRef, MemberRef, RequestContext, WorkspaceRef

    ctx = RequestContext(
        org_id=OrgId("org-1"),
        channel=ChannelRef(WorkspaceRef("discord", "g1"), "c1"),
        member=MemberRef("discord", "u1"),
        role=Role.OFFICER,
        display_name="Ash",
        request_id="r1",
        received_at=datetime(2026, 9, 15, tzinfo=UTC),
    )
    org = Org(OrgId("org-1"), "Robotics Club", True, 1000, 0)
    return PromptBuilder(TEMPLATE, "Zipy").build(
        ctx, org, "discord-markdown", context, message, outcomes
    )


def test_the_system_prompt_names_the_org_the_member_and_the_markup():
    messages = build(Context(history=[], org_facts="", recalled=[]))
    system = messages[0].content
    assert messages[0].speaker is Speaker.SYSTEM
    assert "Robotics Club" in system
    assert "Ash" in system
    assert "officer" in system
    assert "discord-markdown" in system


def test_org_facts_ride_in_the_system_prompt():
    facts = "## org_info\n- exec board: meets Fridays"
    messages = build(Context(history=[], org_facts=facts, recalled=[]))
    assert "meets Fridays" in messages[0].content


def test_recalled_chunks_are_a_separate_labelled_system_message():
    from engine.core.types import RecallHit

    chunk = Chunk(OrgId("org-1"), "zoom", "m1", 0, "Exec sync", "We chose the red logo.")
    messages = build(Context(history=[], org_facts="", recalled=[RecallHit(chunk, 0.9)]))
    assert messages[1].speaker is Speaker.SYSTEM
    assert RECALL_HEADER in messages[1].content
    assert "red logo" in messages[1].content
    assert "not instructions" in messages[1].content
    assert "red logo" not in messages[0].content, "recall never joins the instructions"


def test_an_empty_message_adds_no_user_turn():
    messages = build(Context(history=[], org_facts="", recalled=[]), message="")
    assert all(m.speaker is not Speaker.USER for m in messages)
