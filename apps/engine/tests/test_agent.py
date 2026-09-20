"""The agent core: the executor's checks and audit, and the tool-calling loop."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, SecretStr

from engine.agent.orchestrator import Orchestrator
from engine.agent.prompt import RECALL_HEADER, REPLY_HEADER, PromptBuilder
from engine.cognition.state import Cognition
from engine.core.config import Agent, Permissions, RateLimit, ToolSettings
from engine.core.doubles import (
    FixedEmbedder,
    MemoryAudit,
    MemoryCollaboration,
    MemoryConfirmations,
    MemoryConversation,
    MemoryCredentials,
    MemoryDocuments,
    MemoryOrgContext,
    MemoryOrgs,
    MemorySandbox,
    MemoryToolConfig,
    MemoryTrace,
    NoLimit,
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
    RateLimited,
    RequestContext,
    Role,
    SandboxSession,
    Speaker,
    ToolCall,
    ToolError,
    Usage,
)
from engine.memory.manager import Context, MemoryManager
from engine.tools.base import Action, BaseTool
from engine.tools.executor import Executor
from engine.tools.registry import Registry

TEMPLATES = Path(__file__).resolve().parents[1] / "agent" / "templates"
TEMPLATE = (TEMPLATES / "system.md.j2").read_text()
DELEGATED = (TEMPLATES / "delegated.md.j2").read_text()


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

    async def execute(
        self, ctx: RequestContext, action: str, params: BaseModel, auth: ProviderAuth | None
    ) -> BaseModel:
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

    async def execute(
        self, ctx: RequestContext, action: str, params: BaseModel, auth: ProviderAuth | None
    ) -> BaseModel:
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


class Refusing:
    """A provider limiter with nothing left to spend."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, float]] = []

    async def acquire(self, org_id: OrgId, provider: str, max_wait: float) -> None:  # noqa: ARG002 - protocol signature
        """Refuse every call."""
        self.asked.append((provider, max_wait))
        raise RateLimited(f"{provider} is at its limit for this org")


def executor(
    ctx: Any,
    credentials: MemoryCredentials | None = None,
    audit: MemoryAudit | None = None,
    limiter: Any = None,
    limits: RateLimit | None = None,
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
            limiter=limiter if limiter is not None else NoLimit(),
            limits=limits or RateLimit(),
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


async def test_a_call_over_the_provider_limit_comes_back_as_a_failure_and_is_audited(ctx):
    limiter = Refusing()
    run, audit = executor(ctx, limiter=limiter)
    outcome = await run.run(ctx, call("diary.list_events", day="friday"))
    assert not outcome.ok
    assert "limit" in outcome.content
    # The org sees why the call did not happen, and the attempt is on the record.
    assert [(e.action, e.ok) for e in audit.entries] == [("diary.list_events", False)]


async def test_a_refused_call_never_reaches_the_provider(ctx):
    run, _ = executor(ctx, limiter=Refusing())
    outcome = await run.run(ctx, call("diary.book", title="standup"))
    assert not outcome.ok
    assert "the provider said no" not in outcome.content


async def test_the_wait_budget_of_a_tool_call_comes_from_the_config(ctx):
    limiter = Refusing()
    run, _ = executor(ctx, limiter=limiter, limits=RateLimit(provider_max_wait_seconds=2.5))
    await run.run(ctx, call("diary.list_events", day="friday"))
    assert limiter.asked == [("google", 2.5)]


async def test_a_tool_over_no_provider_is_never_rate_limited(ctx):
    limiter = NoLimit()
    run, _ = executor(ctx, limiter=limiter)
    await run.run(ctx, call("diary.list_events", day="friday"))
    # diary runs over google, so this records one. A providerless tool would record none.
    assert [provider for _, provider in limiter.taken] == ["google"]


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
    agent_config: Agent | None = None,
    trace: MemoryTrace | None = None,
    sandbox: MemorySandbox | None = None,
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
        cognition=Cognition(
            store=MemoryCollaboration(),
            settings=cfg.collaboration,
        ),
    )
    model = ScriptedModel(script=script)
    held = confirmations if confirmations is not None else MemoryConfirmations()
    run, _ = executor(ctx, audit=audit)
    agent = Orchestrator(
        agent=agent_config or Agent(max_iterations=max_iterations),
        model=model,
        memory=memory,
        prompts=PromptBuilder(TEMPLATE, "Zipy", DELEGATED),
        registry=registry(),
        executor=run,
        orgs=orgs,
        credentials=connected(ctx.org_id),
        tool_config=MemoryToolConfig(),
        confirmations=held,
        trace=trace or MemoryTrace(),
        sandbox=sandbox,
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


def build(context: Context, message: str = "hi", outcomes=(), reply_to: str = "") -> list[Any]:
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
        reply_to=reply_to,
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


def test_a_reply_quotes_the_message_it_answers_just_before_the_user_turn():
    messages = build(
        Context(history=[], org_facts="", recalled=[]),
        message="and the week after?",
        reply_to="The next exec sync is Friday at 5.",
    )
    quoted = next(i for i, m in enumerate(messages) if REPLY_HEADER in m.content)
    asked = next(i for i, m in enumerate(messages) if m.content == "and the week after?")
    assert messages[quoted].speaker is Speaker.SYSTEM
    assert "Friday at 5" in messages[quoted].content
    assert quoted + 1 == asked, "the quote is the immediate context of the question"


def test_replying_to_nothing_writes_no_quote():
    messages = build(Context(history=[], org_facts="", recalled=[]))
    assert all(REPLY_HEADER not in m.content for m in messages)


def test_an_empty_message_adds_no_user_turn():
    messages = build(Context(history=[], org_facts="", recalled=[]), message="")
    assert all(m.speaker is not Speaker.USER for m in messages)


async def test_calls_costing_less_than_a_cent_still_reach_the_spend(ctx, cfg):
    # A cheap model costs a fraction of a cent a call. Rounding each one to whole cents would
    # leave the spend at zero forever and the budget would never bite.
    answer = Completion(text="ok", usage=Usage(10, 5, 0.2))
    agent, _, orgs, _ = orchestrator(ctx, cfg, [answer, answer, answer], budget_cents=100)
    for _ in range(3):
        await agent.handle(ctx, "hello", "discord-markdown")
    assert orgs.orgs[ctx.org_id].spent_cents == pytest.approx(0.6)


def test_every_tool_names_what_it_acted_on_for_the_audit_log():
    # The audit trail records a target; an empty one leaves every entry looking alike.
    from engine.core.config import load as load_config
    from engine.tools.registry import Registry as ToolRegistry

    registry = ToolRegistry(load_config().tools)
    named = {
        "calendar.update_event": {"eventId": "e1"},
        "calendar.delete_event": {"eventId": "e1"},
        "drive.read_file_content": {"fileId": "fl-1"},
        "gmail.get_thread": {"threadId": "th-1"},
        "notion.get_page": {"page_id": "p1"},
        "search.web_search": {"query": "asu robotics"},
    }
    for qualified_name, arguments in named.items():
        tool_name, action = registry.resolve(qualified_name)
        cls = registry.tool_class(tool_name)
        params = cls.actions[action].params.model_validate(arguments)
        tool = cls(registry.settings_for(tool_name))
        assert tool.target(action, params), f"{qualified_name} records no target"


def test_the_collaboration_block_is_absent_until_there_is_something_to_say():
    """A run with collaboration off is byte for byte a run without the feature."""
    without = build(Context(history=[], org_facts="", recalled=[]))
    off = build(Context(history=[], org_facts="", recalled=[], collaborator=""))

    assert off[0].content == without[0].content
    assert "How this person works" not in off[0].content


def test_a_collaboration_block_rides_in_the_system_prompt_and_yields_to_the_rules():
    asked = "- Answer briefly. Lead with the result."
    messages = build(Context(history=[], org_facts="", recalled=[], collaborator=asked))
    system = messages[0].content

    assert "How this person works" in system
    assert asked in system
    # It is a preference, not a permission.
    assert "never override" in system


# ---------------------------------------------------------------- delegation


def _delegate(task="find the open CI issues", tools=("diary",), id_="d1"):
    from engine.core.types import ToolCall

    return ToolCall(id=id_, name="delegate", arguments={"task": task, "tools": list(tools)})


async def test_a_delegate_call_runs_the_loop_again_and_comes_back_as_a_tool_result(ctx, cfg):
    agent, model, _, _ = orchestrator(
        ctx,
        cfg,
        [
            Completion(text="", tool_calls=(_delegate(),)),
            Completion(text="Two issues, both about the image build."),
            Completion(text="There are two, both the image build."),
        ],
    )

    result = await agent.handle(ctx, "what is failing in CI?", "discord-markdown")

    assert isinstance(result, AgentReply)
    assert result.text == "There are two, both the image build."
    # The sub-agent's conclusion reached the parent as a tool message.
    parent_second = model.requests[2]
    assert any("both about the image build" in m.content for m in parent_second)


async def test_a_sub_agent_starts_from_the_task_and_not_the_conversation(ctx, cfg):
    agent, model, _, _ = orchestrator(
        ctx,
        cfg,
        [
            Completion(text="", tool_calls=(_delegate(task="count the open issues"),)),
            Completion(text="Two."),
            Completion(text="Two."),
        ],
    )

    await agent.handle(ctx, "what is failing in CI?", "discord-markdown")

    sub = model.requests[1]
    assert len(sub) == 1, "one system message, no history and no user turn"
    assert "count the open issues" in sub[0].content
    assert "what is failing in CI?" not in sub[0].content


async def test_a_sub_agents_workspace_goes_when_it_ends(ctx, cfg):
    """Its files were for the subtask. Leaving them costs memory and leaks into the next one."""
    box = MemorySandbox()
    box.live = [
        SandboxSession(
            name="zipy-sb-sub-build",
            org_id=str(ctx.org_id),
            member="discord:u1",
            started_at=datetime(2026, 9, 19, tzinfo=UTC),
            idle_secs=1.0,
        )
    ]
    agent, _, _, _ = orchestrator(
        ctx,
        cfg,
        [
            Completion(text="", tool_calls=(_delegate(),)),
            Completion(text="Two issues."),
            Completion(text="Two."),
        ],
        sandbox=box,
    )

    await agent.handle(ctx, "what is failing in CI?", "discord-markdown")

    assert box.reaped == ["zipy-sb-sub-build"]


async def test_a_sub_agent_that_failed_still_gives_its_workspace_back(ctx, cfg):
    box = MemorySandbox()
    box.live = [
        SandboxSession(
            name="zipy-sb-sub-build",
            org_id=str(ctx.org_id),
            member="discord:u1",
            started_at=datetime(2026, 9, 19, tzinfo=UTC),
            idle_secs=1.0,
        )
    ]
    agent, _, _, _ = orchestrator(
        ctx,
        cfg,
        [
            Completion(text="", tool_calls=(_delegate(),), usage=Usage(10, 5, 4.0)),
            Completion(text="never read", usage=Usage(10, 5, 90.0)),
        ],
        budget_cents=5,
        sandbox=box,
    )

    # The sub-agent runs out of budget, and the parent runs out on its next turn.
    with pytest.raises(BudgetExceeded):
        await agent.handle(ctx, "what is failing in CI?", "discord-markdown")

    assert box.reaped == ["zipy-sb-sub-build"], "the workspace went back even though it failed"


async def test_delegation_runs_without_a_sandbox_wired(ctx, cfg):
    agent, _, _, _ = orchestrator(
        ctx,
        cfg,
        [
            Completion(text="", tool_calls=(_delegate(),)),
            Completion(text="Two issues."),
            Completion(text="Two."),
        ],
    )

    result = await agent.handle(ctx, "what is failing in CI?", "discord-markdown")

    assert isinstance(result, AgentReply)


async def test_a_sub_agent_is_not_offered_the_delegate_tool(ctx, cfg):
    """Two levels is the bound. A sub-agent that could delegate would not be bounded."""
    from engine.agent import delegate as delegation

    agent, _, _, _ = orchestrator(
        ctx,
        cfg,
        [
            Completion(text="", tool_calls=(_delegate(),)),
            Completion(text="", tool_calls=(_delegate(id_="d2"),)),
            Completion(text="done"),
            Completion(text="done"),
        ],
    )

    await agent.handle(ctx, "go", "discord-markdown")

    # The nested delegate call was refused rather than run.
    assert delegation.SUB_AGENT_DEPTH == 1


async def test_a_nested_delegate_is_refused_as_a_failed_tool_not_an_error(ctx, cfg):
    agent, model, _, _ = orchestrator(
        ctx,
        cfg,
        [
            Completion(text="", tool_calls=(_delegate(),)),
            Completion(text="", tool_calls=(_delegate(id_="d2"),)),
            Completion(text="I could not delegate further."),
            Completion(text="Done anyway."),
        ],
    )

    result = await agent.handle(ctx, "go", "discord-markdown")

    assert isinstance(result, AgentReply)
    sub_second = model.requests[2]
    assert any("cannot delegate again" in m.content for m in sub_second)


async def test_a_request_runs_at_most_max_delegations_sub_agents(ctx, cfg):
    config = Agent(max_iterations=8, max_delegations=1)
    agent, model, _, _ = orchestrator(
        ctx,
        cfg,
        [
            Completion(text="", tool_calls=(_delegate(),)),
            Completion(text="first done"),
            Completion(text="", tool_calls=(_delegate(id_="d2"),)),
            Completion(text="Only one ran."),
        ],
        agent_config=config,
    )

    result = await agent.handle(ctx, "go", "discord-markdown")

    assert isinstance(result, AgentReply)
    last = model.requests[-1]
    assert any("already ran 1" in m.content for m in last)


async def test_a_sub_agent_gets_its_own_shorter_turn_limit(ctx, cfg):
    """It loops without answering, and stops at delegate_max_iterations, not the parent's."""
    config = Agent(max_iterations=8, delegate_max_iterations=2)
    calling = Completion(text="", tool_calls=(call("diary.list_events"),))
    agent, model, _, _ = orchestrator(
        ctx,
        cfg,
        [
            Completion(text="", tool_calls=(_delegate(),)),
            calling,
            calling,
            Completion(text="Fine."),
        ],
        agent_config=config,
    )

    result = await agent.handle(ctx, "go", "discord-markdown")

    assert isinstance(result, AgentReply)
    assert len(model.script) == 0, "two sub-agent turns, then the parent"


async def test_a_sub_agent_only_gets_the_tools_the_parent_named(ctx, cfg):
    from engine.agent.delegate import tools_of

    asked = _delegate(tools=("diary", "ghost"))
    assert tools_of(asked, ["diary", "search"]) == ["diary"], "a tool the org lacks is dropped"
    assert tools_of(_delegate(tools=()), ["diary"]) == []


async def test_a_delegate_call_with_no_task_is_a_failed_tool(ctx, cfg):
    from engine.core.types import ToolCall

    empty = ToolCall(id="d1", name="delegate", arguments={"task": "  ", "tools": []})
    agent, model, _, _ = orchestrator(
        ctx,
        cfg,
        [Completion(text="", tool_calls=(empty,)), Completion(text="I need a task.")],
    )

    result = await agent.handle(ctx, "go", "discord-markdown")

    assert isinstance(result, AgentReply)
    assert any("no task" in m.content for m in model.requests[-1])


async def test_the_spend_of_a_sub_agent_is_charged_to_the_org(ctx, cfg):
    agent, _, orgs, _ = orchestrator(
        ctx,
        cfg,
        [
            Completion(text="", tool_calls=(_delegate(),), usage=Usage(10, 5, 1.0)),
            Completion(text="done", usage=Usage(10, 5, 2.0)),
            Completion(text="Answered.", usage=Usage(10, 5, 4.0)),
        ],
    )

    await agent.handle(ctx, "go", "discord-markdown")

    assert orgs.orgs[ctx.org_id].spent_cents == 7, "parent and sub-agent both charged"


async def test_every_sub_agent_event_says_which_level_and_which_call_it_belongs_to(ctx, cfg):
    trace = MemoryTrace()
    agent, _, _, _ = orchestrator(
        ctx,
        cfg,
        [
            Completion(text="", tool_calls=(_delegate(),)),
            Completion(text="done"),
            Completion(text="Answered."),
        ],
        trace=trace,
    )

    await agent.handle(ctx, "go", "discord-markdown")

    named = {name for name, _ in trace.events}
    assert "delegate" in named and "delegate_done" in named
    nested = [(name, parent) for name, depth, parent in trace.levels if depth == 1]
    assert nested, "the sub-agent raised events"
    assert all(parent == "d1" for _, parent in nested), "each names the delegate call"
    assert {name for name, _ in nested} >= {"model_started", "reply"}
    outer = [name for name, depth, parent in trace.levels if depth == 0 and not parent]
    assert "delegate" in outer, "the handoff itself is the parent's event"


async def test_delegation_off_offers_no_such_tool(ctx, cfg):
    from engine.agent.delegate import NAME

    agent, _, _, _ = orchestrator(
        ctx, cfg, [Completion(text="Answered.")], agent_config=Agent(delegate=False)
    )
    schemas = await agent._schemas(ctx)  # noqa: SLF001
    assert all(s["function"]["name"] != NAME for s in schemas)


async def test_delegation_on_offers_it_to_the_parent_only(ctx, cfg):
    from engine.agent.delegate import NAME, SUB_AGENT_DEPTH

    agent, _, _, _ = orchestrator(ctx, cfg, [Completion(text="Answered.")])
    parent = await agent._schemas(ctx, 0)  # noqa: SLF001
    sub = await agent._schemas(ctx, SUB_AGENT_DEPTH)  # noqa: SLF001
    assert any(s["function"]["name"] == NAME for s in parent)
    assert all(s["function"]["name"] != NAME for s in sub)


async def test_the_parent_reads_back_what_the_sub_agent_ran(ctx, cfg):
    """So it does not repeat the lookups the sub-agent already made."""
    agent, model, _, _ = orchestrator(
        ctx,
        cfg,
        [
            Completion(text="", tool_calls=(_delegate(),)),
            Completion(text="", tool_calls=(call("diary.list_events"),)),
            Completion(text="Two events."),
            Completion(text="Two."),
        ],
    )

    await agent.handle(ctx, "go", "discord-markdown")

    handed_back = [m.content for m in model.requests[-1] if "delegate ran" in m.content]
    assert handed_back, "the parent was told what it ran"
    assert "diary.list_events" in handed_back[0]


async def test_a_destructive_call_inside_a_sub_agent_stops_and_stores_the_sub_agent(ctx, cfg):
    held = MemoryConfirmations()
    agent, _, _, _ = orchestrator(
        ctx,
        cfg,
        [
            Completion(text="", tool_calls=(_delegate(),)),
            Completion(text="", tool_calls=(call("diary.move_event", event_id="e1"),)),
        ],
        confirmations=held,
    )

    result = await agent.handle(ctx, "clear my week", "discord-markdown")

    assert isinstance(result, NeedsConfirmation)
    stored = held.pending[result.pending.id]
    assert stored.sub_agent is not None
    assert stored.sub_agent.call_id == "d1", "it names the delegate call the parent waits on"
    assert stored.sub_agent.tools == ("diary",)
    assert stored.sub_agent.turns_used == 1
    assert stored.sub_agent.messages, "its conversation is what nothing else holds"


async def test_confirming_takes_the_sub_agent_up_again_and_answers_the_parent(ctx, cfg):
    held = MemoryConfirmations()
    agent, model, _, _ = orchestrator(
        ctx,
        cfg,
        [
            Completion(text="", tool_calls=(_delegate(),)),
            Completion(text="", tool_calls=(call("diary.move_event", event_id="e1"),)),
            # After the answer: the sub-agent finishes, then the parent answers.
            Completion(text="Removed the one clash."),
            Completion(text="Cleared it."),
        ],
        confirmations=held,
    )
    stopped = await agent.handle(ctx, "clear my week", "discord-markdown")
    assert isinstance(stopped, NeedsConfirmation)

    result = await agent.confirm(ctx, stopped.pending.id, "discord-markdown")

    assert isinstance(result, AgentReply)
    assert result.text == "Cleared it."
    # The parent was handed the subtask's conclusion, not the raw tool result.
    parent = model.requests[-1]
    assert any("Removed the one clash." in m.content for m in parent)


async def test_a_resumed_sub_agent_picks_up_the_turns_it_had_left(ctx, cfg):
    """It had taken one of two; one is left, so it answers or runs out on that one."""
    config = Agent(max_iterations=8, delegate_max_iterations=2)
    held = MemoryConfirmations()
    agent, model, _, _ = orchestrator(
        ctx,
        cfg,
        [
            Completion(text="", tool_calls=(_delegate(),)),
            Completion(text="", tool_calls=(call("diary.move_event", event_id="e1"),)),
            Completion(text="Done."),
            Completion(text="All set."),
        ],
        confirmations=held,
        agent_config=config,
    )
    stopped = await agent.handle(ctx, "go", "discord-markdown")
    assert isinstance(stopped, NeedsConfirmation)

    result = await agent.confirm(ctx, stopped.pending.id, "discord-markdown")

    assert isinstance(result, AgentReply)
    assert len(model.script) == 0


async def test_a_sub_agent_with_no_turns_left_does_not_resume(ctx, cfg):
    config = Agent(max_iterations=8, delegate_max_iterations=1)
    held = MemoryConfirmations()
    agent, model, _, _ = orchestrator(
        ctx,
        cfg,
        [
            Completion(text="", tool_calls=(_delegate(),)),
            Completion(text="", tool_calls=(call("diary.move_event", event_id="e1"),)),
            Completion(text="I could not finish that."),
        ],
        confirmations=held,
        agent_config=config,
    )
    stopped = await agent.handle(ctx, "go", "discord-markdown")
    assert isinstance(stopped, NeedsConfirmation)

    result = await agent.confirm(ctx, stopped.pending.id, "discord-markdown")

    assert isinstance(result, AgentReply)
    assert any("ran out of turns" in m.content for m in model.requests[-1])


async def test_a_confirmation_the_request_itself_asked_for_stores_no_sub_agent(ctx, cfg):
    """The ordinary path is unchanged: nothing is kept that was not kept before."""
    held = MemoryConfirmations()
    agent, _, _, _ = orchestrator(
        ctx,
        cfg,
        [Completion(text="", tool_calls=(call("diary.move_event", event_id="e1"),))],
        confirmations=held,
    )

    result = await agent.handle(ctx, "delete it", "discord-markdown")

    assert isinstance(result, NeedsConfirmation)
    assert held.pending[result.pending.id].sub_agent is None
