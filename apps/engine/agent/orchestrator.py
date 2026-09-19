"""The tool-calling loop for one request.

Budget check, memory, tool schemas, then up to max_iterations model calls. Read and create calls
run at once; the first destructive call stops the loop and returns NeedsConfirmation, which the
gateway asks on the platform and resumes with confirm. Every model call adds its cost to the
org's spend.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Any
from uuid import uuid4

from engine.agent import delegate as delegation
from engine.agent.classifier import needs_confirmation
from engine.agent.prompt import PromptBuilder, tool_messages
from engine.core.config import Agent
from engine.core.protocols import (
    ChatModel,
    ConfirmationStore,
    CredentialStore,
    OrgStore,
    ToolConfigStore,
    TraceSink,
)
from engine.core.types import (
    AgentReply,
    AgentResult,
    BudgetExceeded,
    ChatMessage,
    Completion,
    ConfigError,
    ConfirmationError,
    Dimension,
    Evidence,
    NeedsConfirmation,
    Org,
    PendingConfirmation,
    RequestContext,
    Signal,
    StoreError,
    SubAgent,
    ToolCall,
    ToolOutcome,
    Usage,
    ZipyError,
)
from engine.memory.manager import MemoryManager
from engine.tools.executor import Executor
from engine.tools.registry import Registry


def _total(usage: Usage, added: Usage) -> Usage:
    """Two usages summed."""
    return Usage(
        prompt_tokens=usage.prompt_tokens + added.prompt_tokens,
        completion_tokens=usage.completion_tokens + added.completion_tokens,
        cost_cents=usage.cost_cents + added.cost_cents,
    )


def _answered(evidence: Evidence, target: float) -> Signal:
    """What answering a confirmation shows about how much the asker wants to be asked."""
    return Signal(dimension=Dimension.AUTONOMY, target=target, evidence=evidence)


@dataclass
class Budget:
    """What one request has spent that is not money: how many sub-agents it has run.

    The orchestrator holds no per-request state, so this is made per request and threaded down.
    A counter on the instance would be shared by every request in flight.
    """

    delegations: int = 0


def _task_of(messages: Sequence[ChatMessage]) -> str:
    """The task a sub-agent was given, which is the system message it started from."""
    return messages[0].content if messages else ""


def _failed(call: ToolCall, why: str) -> ToolOutcome:
    """A delegate call the parent reads as a failed tool rather than a raised error."""
    return ToolOutcome(call=call, ok=False, content=f"delegate did not run: {why}")


def _summarize(call: ToolCall) -> str:
    """One line naming a call and its arguments, shown to whoever confirms it."""
    arguments = ", ".join(f"{key}={value!r}" for key, value in sorted(call.arguments.items()))
    return f"{call.name}({arguments})" if arguments else f"{call.name}()"


class Orchestrator:
    """Runs requests. Holds no per-request state; everything per request is in RequestContext."""

    def __init__(
        self,
        agent: Agent,
        model: ChatModel,
        memory: MemoryManager,
        prompts: PromptBuilder,
        registry: Registry,
        executor: Executor,
        orgs: OrgStore,
        credentials: CredentialStore,
        tool_config: ToolConfigStore,
        confirmations: ConfirmationStore,
        trace: TraceSink,
    ) -> None:
        self._agent = agent
        self._model = model
        self._memory = memory
        self._prompts = prompts
        self._registry = registry
        self._executor = executor
        self._orgs = orgs
        self._credentials = credentials
        self._tool_config = tool_config
        self._confirmations = confirmations
        self._trace = trace

    async def handle(self, ctx: RequestContext, message: str, markup: str) -> AgentResult:
        """Answer one message, or stop at a destructive call. Over budget is BudgetExceeded.

        markup is the formatting the platform renders.
        """
        org = await self._org(ctx)
        context = await self._memory.build(ctx, message)
        offered = await self._offered(ctx)
        messages = self._prompts.build(ctx, org, markup, context, message, tools=offered)
        return await self._run(ctx, org, messages, Budget())

    async def confirm(self, ctx: RequestContext, confirmation_id: str, markup: str) -> AgentResult:
        """Run a confirmed call and continue the loop. Expired or foreign is ConfirmationError."""
        pending = await self._confirmations.take(confirmation_id, ctx.received_at)
        if pending is None:
            raise ConfirmationError(f"confirmation {confirmation_id} is unknown or expired")
        if pending.org_id != ctx.org_id:
            raise ConfirmationError(f"confirmation {confirmation_id} belongs to another org")
        org = await self._org(ctx)
        outcome = await self._executor.run(ctx, pending.call)
        self._trace.event(
            ctx, "confirmation", {"id": confirmation_id, "answer": "confirm", "ok": outcome.ok}
        )
        await self._memory.observe(ctx, [_answered(Evidence.CONFIRMATION_CONFIRMED, 1.0)])
        resumed = outcome
        if pending.sub_agent is not None:
            resumed = await self._resume(ctx, org, pending.sub_agent, outcome)
        context = await self._memory.build(ctx, pending.summary)
        offered = await self._offered(ctx)
        messages = self._prompts.build(ctx, org, markup, context, "", (resumed,), offered)
        return await self._run(ctx, org, messages, Budget())

    async def _resume(
        self, ctx: RequestContext, org: Org, sub: SubAgent, outcome: ToolOutcome
    ) -> ToolOutcome:
        """Take a sub-agent up again with its confirmed call answered, and hand back what it made.

        What comes out is the delegate call's result, not the confirmed tool's: the parent asked
        for a subtask and is owed the subtask's conclusion.
        """
        call = ToolCall(id=sub.call_id, name=delegation.NAME, arguments={"task": sub.task})
        nested = replace(ctx, depth=delegation.SUB_AGENT_DEPTH, parent=sub.call_id)
        messages = [*sub.messages, *tool_messages([outcome])]
        left = self._agent.delegate_max_iterations - sub.turns_used
        if left < 1:
            return _failed(call, "the subtask ran out of turns while it waited")
        self._trace.event(nested, "delegate_resumed", {"id": sub.call_id, "turns_left": left})
        try:
            result = await self._run(nested, org, messages, Budget(), only=sub.tools, left=left)
        except ZipyError as exc:
            return _failed(call, str(exc))
        if not isinstance(result, AgentReply):
            return _failed(call, "that subtask needs another confirmation, so do it yourself")
        return ToolOutcome(
            call=call, ok=True, content=delegation.result(result.text, list(result.ran))
        )

    async def cancel(self, ctx: RequestContext, confirmation_id: str) -> None:
        """Drop a pending call."""
        pending = await self._confirmations.take(confirmation_id, ctx.received_at)
        if pending is not None and pending.org_id != ctx.org_id:
            raise ConfirmationError(f"confirmation {confirmation_id} belongs to another org")
        self._trace.event(ctx, "confirmation", {"id": confirmation_id, "answer": "cancel"})
        await self._memory.observe(ctx, [_answered(Evidence.CONFIRMATION_CANCELLED, 0.0)])

    async def _org(self, ctx: RequestContext) -> Org:
        """The org of the request. An org that is not stored is a StoreError."""
        org = await self._orgs.get(ctx.org_id)
        if org is None:
            raise StoreError(f"org {ctx.org_id} is not stored")
        return org

    async def _offered(self, ctx: RequestContext, only: Sequence[str] | None = None) -> list[str]:
        """The tools this org has connected and enabled, narrowed to only when one is given."""
        connected = await self._credentials.connected(ctx.org_id)
        overrides = await self._tool_config.overrides(ctx.org_id)
        available = self._registry.available(connected, overrides)
        if only is None:
            return available
        return [name for name in available if name in only]

    async def _schemas(
        self, ctx: RequestContext, depth: int = 0, only: Sequence[str] | None = None
    ) -> list[dict[str, Any]]:
        """The schemas one level is offered. Only the parent is offered delegation."""
        tools = await self._offered(ctx, only)
        schemas = self._registry.schemas(tools)
        if depth == 0 and self._agent.delegate:
            schemas.append(delegation.schema(tools))
        return schemas

    async def _run(
        self,
        ctx: RequestContext,
        org: Org,
        messages: list[ChatMessage],
        budget: Budget,
        only: Sequence[str] | None = None,
        left: int = 0,
    ) -> AgentResult:
        """Call the model until it answers, a destructive call waits, or the turns run out.

        ctx.depth is 0 for the request and 1 for a sub-agent, and travels onto every event every
        layer raises, so the flat trace can be read as the tree it is. only narrows the tools.
        """
        depth = ctx.depth
        schemas = await self._schemas(ctx, depth, only)
        limit = left or (
            self._agent.max_iterations if depth == 0 else self._agent.delegate_max_iterations
        )
        usage = Usage()
        spent = float(org.spent_cents)
        ran: list[str] = []
        for turn in range(1, limit + 1):
            if spent >= org.budget_cents:
                raise BudgetExceeded(
                    f"{org.name} has spent its {org.budget_cents} cent monthly budget"
                )
            self._trace.event(ctx, "model_started", {"turn": turn})
            completion = await self._model.complete(ctx, messages, schemas)
            usage = _total(usage, completion.usage)
            spent += completion.usage.cost_cents
            await self._orgs.add_spend(ctx.org_id, completion.usage.cost_cents)
            self._trace.event(ctx, "model_call", self._call_event(turn, completion))
            if not completion.tool_calls:
                self._trace.event(ctx, "answer_draft", {"text": completion.text})
                self._trace.event(ctx, "reply", {"turns": turn, "tools": ran})
                return AgentReply(text=completion.text, usage=usage, ran=tuple(ran))
            runnable, held = self._split(completion.tool_calls)
            outcomes: list[ToolOutcome] = []
            for call in runnable:
                if call.name == delegation.NAME:
                    sub, spent = await self._delegate(ctx, org, call, budget, spent)
                    if isinstance(sub, NeedsConfirmation):
                        return sub
                    outcomes.append(sub)
                    continue
                outcomes.append(await self._executor.run(ctx, call))
            ran.extend(outcome.call.name for outcome in outcomes)
            if held is not None:
                messages.extend(tool_messages(outcomes))
                return await self._hold(ctx, held, self._suspended(ctx, messages, turn, only))
            messages.extend(tool_messages(outcomes))
        self._trace.event(ctx, "reply", {"turns": limit, "tools": ran})
        return AgentReply(text=self._exhausted(ran), usage=usage, ran=tuple(ran))

    def _suspended(
        self,
        ctx: RequestContext,
        messages: list[ChatMessage],
        turn: int,
        only: Sequence[str] | None,
    ) -> SubAgent | None:
        """What a sub-agent needs to take itself up again. None when the request itself is asking.

        The parent is not kept: what it was doing is rebuilt from the platform's history and the
        result this sub-agent goes on to produce, the way a resumed request already is.
        """
        if not ctx.depth or not ctx.parent:
            return None
        return SubAgent(
            call_id=ctx.parent,
            task=_task_of(messages),
            tools=tuple(only or ()),
            messages=tuple(messages),
            turns_used=turn,
        )

    async def _delegate(
        self,
        ctx: RequestContext,
        org: Org,
        call: ToolCall,
        budget: Budget,
        spent: float,
    ) -> tuple[ToolOutcome | NeedsConfirmation, float]:
        """Run one sub-agent and return what the parent reads, with the spend it left behind.

        Every way this can go wrong is a tool result rather than a raised error: a sub-agent that
        could not finish is one failed call in a request the parent may still answer.
        """
        if ctx.depth >= delegation.SUB_AGENT_DEPTH:
            return _failed(call, "a sub-agent cannot delegate again"), spent
        budget.delegations += 1
        if budget.delegations > self._agent.max_delegations:
            return _failed(call, f"this request already ran {self._agent.max_delegations}"), spent
        try:
            task = delegation.task_of(call)
        except ConfigError as exc:
            return _failed(call, str(exc)), spent
        tools = delegation.tools_of(call, await self._offered(ctx))
        self._trace.event(ctx, "delegate", {"id": call.id, "task": task, "tools": tools})
        messages = self._prompts.delegated(org, task)
        try:
            result = await self._run(
                replace(ctx, depth=delegation.SUB_AGENT_DEPTH, parent=call.id),
                replace(org, spent_cents=spent),
                messages,
                budget,
                only=tools,
            )
        except ZipyError as exc:
            self._trace.event(ctx, "delegate_failed", {"id": call.id, "error": str(exc)})
            return _failed(call, str(exc)), spent
        if not isinstance(result, AgentReply):
            # The sub-agent stopped at a destructive call and stored itself. The gateway asks, and
            # confirm takes it up again and then rebuilds this level around what it produced.
            self._trace.event(ctx, "delegate_held", {"id": call.id})
            return result, spent
        spent += result.usage.cost_cents
        text = delegation.result(result.text, list(result.ran))
        self._trace.event(ctx, "delegate_done", {"id": call.id, "chars": len(text)})
        return ToolOutcome(call=call, ok=True, content=text), spent

    def _call_event(self, turn: int, completion: Completion) -> dict[str, Any]:
        """What one model call records on the trace. The text itself is not recorded here."""
        return {
            "turn": turn,
            "tool_calls": [call.name for call in completion.tool_calls],
            "prompt_tokens": completion.usage.prompt_tokens,
            "completion_tokens": completion.usage.completion_tokens,
            "cost_cents": completion.usage.cost_cents,
        }

    def _split(self, calls: Sequence[ToolCall]) -> tuple[list[ToolCall], ToolCall | None]:
        """The calls that run now, and the first destructive one, which stops the loop.

        Delegating is never itself destructive, and the registry does not know the name. What a
        sub-agent goes on to call is split the same way, one level down.
        """
        runnable: list[ToolCall] = []
        for call in calls:
            if call.name != delegation.NAME and needs_confirmation(self._registry, call):
                return runnable, call
            runnable.append(call)
        return runnable, None

    async def _hold(
        self, ctx: RequestContext, call: ToolCall, sub_agent: SubAgent | None = None
    ) -> NeedsConfirmation:
        """Store a destructive call for someone to answer, and hand it to the gateway."""
        pending = PendingConfirmation(
            id=str(uuid4()),
            org_id=ctx.org_id,
            requested_by=ctx.member,
            channel=ctx.channel,
            call=call,
            summary=_summarize(call),
            expires_at=ctx.received_at + timedelta(seconds=self._agent.confirmation_ttl_secs),
            sub_agent=sub_agent,
        )
        await self._confirmations.put(pending)
        self._trace.event(
            ctx, "confirmation", {"id": pending.id, "answer": "asked", "action": call.name}
        )
        return NeedsConfirmation(pending=pending)

    def _exhausted(self, ran: Sequence[str]) -> str:
        """What the loop says when it used every turn without the model answering."""
        turns = self._agent.max_iterations
        if not ran:
            return (
                f"I stopped after {turns} turns without reaching an answer, and did nothing. "
                "Ask me again with fewer steps in one go."
            )
        return (
            f"I stopped after {turns} turns before finishing. I ran: {', '.join(ran)}. "
            "Nothing else was done. Ask me to carry on if that is not everything."
        )
