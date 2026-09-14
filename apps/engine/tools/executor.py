"""Runs one tool call: permission, credential, execution, validation, audit."""

from __future__ import annotations

from engine.core.config import Permissions
from engine.core.protocols import AuditLog, CredentialStore, ToolConfigStore, TraceSink
from engine.core.types import RequestContext, ToolCall, ToolOutcome
from engine.tools.registry import Registry


class Executor:
    """Executes tool calls for one process. Holds no per-request state."""

    def __init__(
        self,
        registry: Registry,
        permissions: Permissions,
        credentials: CredentialStore,
        tool_config: ToolConfigStore,
        audit: AuditLog,
        trace: TraceSink,
    ) -> None:
        self._registry = registry
        self._permissions = permissions
        self._credentials = credentials
        self._tool_config = tool_config
        self._audit = audit
        self._trace = trace

    async def run(self, ctx: RequestContext, call: ToolCall) -> ToolOutcome:
        """Execute one call and record it.

        Checks the role against the action type, validates the arguments against the action's
        params model, fetches and decrypts the org's credential, runs the tool, validates its
        result, and appends an audit entry whatever happened. A ZipyError becomes a failed
        ToolOutcome whose content the model reads; anything else propagates.
        """
        raise NotImplementedError
