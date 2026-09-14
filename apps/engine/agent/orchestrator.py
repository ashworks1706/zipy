"""The tool-calling loop for one request.

Budget check, memory, tool schemas, then up to max_iterations model calls. Read and create calls
run at once; the first destructive call stops the loop and returns NeedsConfirmation, which the
gateway asks on the platform and resumes with confirm. Every model call adds its cost to the
org's spend.
"""

from __future__ import annotations

from engine.agent.prompt import PromptBuilder
from engine.core.config import Agent
from engine.core.protocols import (
    ChatModel,
    ConfirmationStore,
    CredentialStore,
    OrgStore,
    ToolConfigStore,
    TraceSink,
)
from engine.core.types import AgentResult, RequestContext
from engine.memory.manager import MemoryManager
from engine.tools.executor import Executor
from engine.tools.registry import Registry


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
        raise NotImplementedError

    async def confirm(self, ctx: RequestContext, confirmation_id: str, markup: str) -> AgentResult:
        """Run a confirmed call and continue the loop. Expired or foreign is ConfirmationError."""
        raise NotImplementedError

    async def cancel(self, ctx: RequestContext, confirmation_id: str) -> None:
        """Drop a pending call."""
        raise NotImplementedError
