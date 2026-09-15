"""The TraceSink over LangFuse: one trace per request, one span per model and tool call."""

from __future__ import annotations

from typing import Any

from langfuse import Langfuse

from engine.core.config import Telemetry
from engine.core.types import RequestContext

#: The event name the chat client emits for one model call, recorded as a generation.
GENERATION = "generation"

#: Keys of a generation event that become LangFuse fields rather than metadata.
_GENERATION_KEYS = frozenset(
    {
        "model",
        "input",
        "output",
        "prompt_tokens",
        "completion_tokens",
        "cost_cents",
    }
)


def context_metadata(ctx: RequestContext) -> dict[str, Any]:
    """Who asked and where, as the metadata every observation carries."""
    return {
        "org_id": ctx.org_id,
        "request_id": ctx.request_id,
        "platform": ctx.channel.platform,
        "workspace_id": ctx.channel.workspace.workspace_id,
        "channel_id": ctx.channel.channel_id,
        "member": ctx.member.user_id,
        "role": ctx.role.value,
    }


class LangfuseTrace:
    """Sends trace events to LangFuse. With no keys configured it records nothing."""

    def __init__(self, telemetry: Telemetry) -> None:
        self._telemetry = telemetry
        self._client: Langfuse | None = None
        public = telemetry.langfuse_public_key.get_secret_value()
        secret = telemetry.langfuse_secret_key.get_secret_value()
        if public and secret:
            self._client = Langfuse(
                public_key=public,
                secret_key=secret,
                host=telemetry.langfuse_host or None,
                environment=telemetry.service_name,
            )

    @property
    def enabled(self) -> bool:
        """True when LangFuse keys are configured."""
        return self._client is not None

    def event(self, ctx: RequestContext, name: str, data: dict[str, Any]) -> None:
        """Record one event under the request's trace."""
        client = self._client
        if client is None:
            return
        # A trace sink never fails a request.
        try:
            trace_id = client.create_trace_id(seed=ctx.request_id)
            if name == GENERATION:
                self._generation(client, trace_id, ctx, data)
            else:
                client.create_event(
                    trace_context={"trace_id": trace_id},
                    name=name,
                    input=data,
                    metadata=context_metadata(ctx),
                )
        except Exception:
            return

    def _generation(
        self, client: Langfuse, trace_id: str, ctx: RequestContext, data: dict[str, Any]
    ) -> None:
        """One model call as a LangFuse generation, with its tokens and cost."""
        extra = {key: value for key, value in data.items() if key not in _GENERATION_KEYS}
        generation = client.start_observation(
            trace_context={"trace_id": trace_id},
            name=GENERATION,
            as_type="generation",
            model=str(data.get("model", "")),
            input=data.get("input"),
            output=data.get("output"),
            usage_details={
                "input": int(data.get("prompt_tokens", 0)),
                "output": int(data.get("completion_tokens", 0)),
            },
            cost_details={"total": float(data.get("cost_cents", 0.0)) / 100.0},
            metadata={**context_metadata(ctx), **extra},
        )
        generation.end()

    def flush(self) -> None:
        """Send everything buffered. Does nothing when LangFuse is not configured."""
        if self._client is not None:
            self._client.flush()
