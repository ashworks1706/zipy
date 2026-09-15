"""Runs one tool call: permission, credential, execution, validation, audit."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ValidationError

from engine.core.config import Permissions
from engine.core.protocols import AuditLog, CredentialStore, ToolConfigStore, TraceSink
from engine.core.types import (
    AuditEntry,
    PermissionDenied,
    ProviderAuth,
    RequestContext,
    ToolCall,
    ToolError,
    ToolOutcome,
    ZipyError,
)
from engine.tools.base import Action, BaseTool, qualified
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
        action_name = ""
        target = ""
        ok = False
        content = ""
        error = ""
        try:
            tool_name, action = self._registry.resolve(call.name)
            action_name = qualified(tool_name, action)
            self._trace.event(
                ctx,
                "tool_started",
                {"id": call.id, "action": action_name, "arguments": dict(call.arguments)},
            )
            tool, spec, params = await self._prepare(ctx, tool_name, action, call)
            target = tool.target(action, params)
            result = await tool.execute(action, params, await self._auth(ctx, type(tool)))
            if not isinstance(result, spec.result):
                raise ToolError(f"{action_name} returned {type(result).__name__}")
            content = result.model_dump_json()
            ok = True
        except ZipyError as exc:
            error = f"{type(exc).__name__}: {exc}"
            content = error
        finally:
            await self._record(ctx, call, action_name, target, ok, error)
        return ToolOutcome(call=call, ok=ok, content=content)

    async def _prepare(
        self, ctx: RequestContext, tool_name: str, action: str, call: ToolCall
    ) -> tuple[BaseTool[BaseModel], Action, BaseModel]:
        """The tool, its action and validated params, once the role may run the action."""
        action_type = self._registry.action_type(qualified(tool_name, action))
        if action_type not in self._permissions.allowed(ctx.role):
            raise PermissionDenied(f"a {ctx.role.value} may not run {action_type.value} actions")
        cls = self._registry.tool_class(tool_name)
        spec = cls.actions[action]
        try:
            params = spec.params.model_validate(call.arguments)
        except ValidationError as exc:
            raise ToolError(f"{qualified(tool_name, action)} arguments are invalid: {exc}") from exc
        overrides = await self._tool_config.overrides(ctx.org_id)
        settings = self._registry.settings_for(tool_name, overrides.get(tool_name))
        return cls(settings), spec, params

    async def _auth(
        self, ctx: RequestContext, cls: type[BaseTool[BaseModel]]
    ) -> ProviderAuth | None:
        """The org's credential for the tool's provider, or None for a tool that needs none."""
        if not cls.provider:
            return None
        return await self._credentials.get(ctx.org_id, cls.provider)

    async def _record(
        self,
        ctx: RequestContext,
        call: ToolCall,
        action: str,
        target: str,
        ok: bool,
        error: str,
    ) -> None:
        """Append the audit entry and trace the call. Arguments are recorded, results are not."""
        await self._audit.append(
            AuditEntry(
                org_id=ctx.org_id,
                actor=ctx.member,
                action=action or call.name,
                target=target,
                payload=dict(call.arguments),
                ok=ok,
                error=error,
                at=datetime.now(UTC),
            )
        )
        self._trace.event(
            ctx,
            "tool_call",
            {
                "id": call.id,
                "action": action or call.name,
                "target": target,
                "ok": ok,
                "error": error,
            },
        )
