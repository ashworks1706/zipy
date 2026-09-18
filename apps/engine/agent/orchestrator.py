"""The tool-calling loop for one request.

Budget check, memory, tool schemas, then up to max_iterations model calls. Read and create calls
run at once; the first destructive call stops the loop and returns NeedsConfirmation, which the
gateway asks on the platform and resumes with confirm. Every model call adds its cost to the
org's spend.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from typing import Any
from uuid import uuid4

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
    ConfirmationError,
    Dimension,
    Evidence,
    NeedsConfirmation,
    Org,
    PendingConfirmation,
    RequestContext,
    Signal,
    StoreError,
    ToolCall,
    Usage,
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
        messages = self._prompts.build(ctx, org, markup, context, message)
        return await self._run(ctx, org, messages)

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
        context = await self._memory.build(ctx, pending.summary)
        messages = self._prompts.build(ctx, org, markup, context, "", (outcome,))
        return await self._run(ctx, org, messages)

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

    async def _schemas(self, ctx: RequestContext) -> list[dict[str, Any]]:
        """The function schemas of the tools this org has connected and enabled."""
        connected = await self._credentials.connected(ctx.org_id)
        overrides = await self._tool_config.overrides(ctx.org_id)
        return self._registry.schemas(self._registry.available(connected, overrides))

    async def _run(self, ctx: RequestContext, org: Org, messages: list[ChatMessage]) -> AgentResult:
        """Call the model until it answers, a destructive call waits, or the turns run out."""
        schemas = await self._schemas(ctx)
        usage = Usage()
        spent = float(org.spent_cents)
        ran: list[str] = []
        for turn in range(1, self._agent.max_iterations + 1):
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
                return AgentReply(text=completion.text, usage=usage)
            runnable, held = self._split(completion.tool_calls)
            outcomes = [await self._executor.run(ctx, call) for call in runnable]
            ran.extend(outcome.call.name for outcome in outcomes)
            if held is not None:
                return await self._hold(ctx, held)
            messages.extend(tool_messages(outcomes))
        self._trace.event(ctx, "reply", {"turns": self._agent.max_iterations, "tools": ran})
        return AgentReply(text=self._exhausted(ran), usage=usage)

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
        """The calls that run now, and the first destructive one, which stops the loop."""
        runnable: list[ToolCall] = []
        for call in calls:
            if needs_confirmation(self._registry, call):
                return runnable, call
            runnable.append(call)
        return runnable, None

    async def _hold(self, ctx: RequestContext, call: ToolCall) -> NeedsConfirmation:
        """Store a destructive call for someone to answer, and hand it to the gateway."""
        pending = PendingConfirmation(
            id=str(uuid4()),
            org_id=ctx.org_id,
            requested_by=ctx.member,
            channel=ctx.channel,
            call=call,
            summary=_summarize(call),
            expires_at=ctx.received_at + timedelta(seconds=self._agent.confirmation_ttl_secs),
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
