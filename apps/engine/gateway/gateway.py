"""The Gateway: one entry point per inbound event, returning what to post."""

from __future__ import annotations

from engine.agent.orchestrator import Orchestrator
from engine.core.config import Budget, Config
from engine.core.protocols import (
    CredentialStore,
    OrgContextStore,
    OrgStore,
    RateLimiter,
    ToolConfigStore,
    WorkspaceStore,
)
from engine.gateway.messages import (
    Capabilities,
    Inbound,
    InboundAnswer,
    Outbound,
    WorkspaceInstalled,
)
from engine.tools.registry import Registry


class Gateway:
    """Handles inbound events from every platform. Holds no per-request state."""

    def __init__(
        self,
        config: Config,
        orchestrator: Orchestrator,
        registry: Registry,
        orgs: OrgStore,
        workspaces: WorkspaceStore,
        org_context: OrgContextStore,
        credentials: CredentialStore,
        tool_config: ToolConfigStore,
        rate_limiter: RateLimiter,
    ) -> None:
        self._config = config
        self._orchestrator = orchestrator
        self._registry = registry
        self._orgs = orgs
        self._workspaces = workspaces
        self._org_context = org_context
        self._credentials = credentials
        self._tool_config = tool_config
        self._rate_limiter = rate_limiter

    async def message(self, event: Inbound, capabilities: Capabilities) -> list[Outbound]:
        """Resolve org and role, rate limit, then an admin command or the agent.

        A workspace with no org is UnknownWorkspace. A confirmation becomes a ConfirmPrompt; text
        is split to the platform's message limit.
        """
        raise NotImplementedError

    async def answer(self, event: InboundAnswer, capabilities: Capabilities) -> list[Outbound]:
        """Confirm or cancel a pending call, if the member may answer it."""
        raise NotImplementedError

    async def installed(self, event: WorkspaceInstalled, budget: Budget) -> list[Outbound]:
        """Create an org for a new workspace, link it, make the installer an admin, welcome."""
        raise NotImplementedError
