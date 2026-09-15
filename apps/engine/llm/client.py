"""The ChatModel over LiteLLM, for one [models.*] role. Spend comes back in Usage."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Sequence
from typing import Any

import litellm
from litellm.exceptions import (
    APIConnectionError,
    InternalServerError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
)

from engine.core.config import ModelRole
from engine.core.protocols import TraceSink
from engine.core.types import (
    ChatMessage,
    Completion,
    ModelError,
    RequestContext,
    Speaker,
    ToolCall,
    Usage,
    from_wire,
    wire_name,
)

#: What a credential is replaced with anywhere it would reach a message.
MASK = "**********"

#: Characters a participant name may carry on the wire.
_NAME_ALLOWED = re.compile(r"[^A-Za-z0-9_-]")

#: Provider failures the caller may retry.
# A dropped connection and a provider 5xx pass on their own, like a timeout does.
RETRYABLE = (
    Timeout,
    RateLimitError,
    TimeoutError,
    APIConnectionError,
    ServiceUnavailableError,
    InternalServerError,
)


def participant_name(name: str) -> str:
    """A speaker name in the character set the wire format allows."""
    return _NAME_ALLOWED.sub("_", name)[:64]


def scrub(text: str, secret: str) -> str:
    """The text with the secret replaced by the mask."""
    return text.replace(secret, MASK) if secret else text


def provider_error(model: str, exc: Exception, secret: str) -> ModelError:
    """A provider exception as a ModelError, with the credential scrubbed out of it."""
    detail = scrub(str(exc), secret)
    return ModelError(f"{model} failed: {detail}", retryable=isinstance(exc, RETRYABLE))


def _tool_call_wire(call: ToolCall) -> dict[str, Any]:
    """One tool call as the assistant turn that asked for it."""
    return {
        "id": call.id,
        "type": "function",
        "function": {"name": wire_name(call.name), "arguments": json.dumps(call.arguments)},
    }


def to_wire(message: ChatMessage) -> dict[str, Any]:
    """One ChatMessage as an OpenAI-style message dict."""
    body: dict[str, Any] = {"role": message.speaker.value, "content": message.content}
    if message.speaker is Speaker.TOOL:
        body["tool_call_id"] = message.tool_call_id
        if message.name:
            body["name"] = wire_name(message.name)
        return body
    if message.tool_calls:
        body["tool_calls"] = [_tool_call_wire(call) for call in message.tool_calls]
        if not message.content:
            body["content"] = None
    if message.name and message.speaker in (Speaker.USER, Speaker.ASSISTANT):
        body["name"] = participant_name(message.name)
    return body


def _arguments(raw: object, function_name: str) -> dict[str, Any]:
    """The arguments of a tool call. Anything but a JSON object is a ModelError."""
    if isinstance(raw, dict):
        return dict(raw)
    text = raw if isinstance(raw, str) else ""
    try:
        parsed = json.loads(text or "{}")
    except json.JSONDecodeError as exc:
        raise ModelError(
            f"the model sent unparsable arguments for {function_name}", retryable=False
        ) from exc
    if not isinstance(parsed, dict):
        raise ModelError(
            f"the model sent non-object arguments for {function_name}", retryable=False
        )
    return dict(parsed)


def tool_calls_of(message: Any) -> tuple[ToolCall, ...]:
    """The tool calls of a response message, under the names the registry resolves."""
    raw = getattr(message, "tool_calls", None) or []
    calls = []
    for index, call in enumerate(raw):
        function = getattr(call, "function", None)
        name = getattr(function, "name", "") or ""
        identifier = getattr(call, "id", "") or f"call_{index}"
        calls.append(
            ToolCall(
                id=identifier,
                name=from_wire(name),
                arguments=_arguments(getattr(function, "arguments", None), name),
            )
        )
    return tuple(calls)


def usage_of(response: Any) -> Usage:
    """Tokens and cost of one response, cost in cents."""
    raw = getattr(response, "usage", None)
    return Usage(
        prompt_tokens=int(getattr(raw, "prompt_tokens", 0) or 0),
        completion_tokens=int(getattr(raw, "completion_tokens", 0) or 0),
        cost_cents=cost_cents(response),
    )


def cost_cents(response: Any) -> float:
    """What the call cost, in cents. An unpriced model costs nothing."""
    hidden = getattr(response, "_hidden_params", None)
    if isinstance(hidden, dict) and hidden.get("response_cost") is not None:
        return float(hidden["response_cost"]) * 100.0
    # An unpriced model costs nothing rather than failing the request.
    try:
        return float(litellm.completion_cost(completion_response=response)) * 100.0
    except Exception:
        return 0.0


class LiteLlmChat:
    """Chat completions with function calling through litellm.acompletion, with fallbacks."""

    def __init__(self, role: ModelRole, trace: TraceSink) -> None:
        self._role = role
        self._trace = trace

    async def complete(
        self,
        ctx: RequestContext,
        messages: Sequence[ChatMessage],
        tools: Sequence[dict[str, Any]],
    ) -> Completion:
        """One model call. Timeouts and rate limits raise a retryable ModelError."""
        wire = [to_wire(message) for message in messages]
        started = time.monotonic()
        try:
            response = await litellm.acompletion(**self._request(wire, tools))
        except Exception as exc:
            raise self._failure(ctx, exc) from exc
        completion = self._completion(response)
        self._trace.event(
            ctx,
            "generation",
            {
                "model": self._role.model,
                "latency_ms": round((time.monotonic() - started) * 1000),
                "input": wire,
                "output": completion.text,
                "tool_calls": [call.name for call in completion.tool_calls],
                "prompt_tokens": completion.usage.prompt_tokens,
                "completion_tokens": completion.usage.completion_tokens,
                "cost_cents": completion.usage.cost_cents,
            },
        )
        return completion

    def _request(
        self, wire: list[dict[str, Any]], tools: Sequence[dict[str, Any]]
    ) -> dict[str, Any]:
        """The keyword arguments of one litellm call."""
        request: dict[str, Any] = {
            "model": self._role.model,
            "messages": wire,
            "temperature": self._role.temperature,
            "max_tokens": self._role.max_tokens,
            "timeout": self._role.timeout_secs,
        }
        key = self._role.api_key.get_secret_value()
        if key:
            request["api_key"] = key
        if self._role.api_base:
            request["api_base"] = self._role.api_base
        if self._role.fallbacks:
            request["fallbacks"] = list(self._role.fallbacks)
        if tools:
            request["tools"] = list(tools)
            request["tool_choice"] = "auto"
        return request

    def _completion(self, response: Any) -> Completion:
        """One litellm response as a Completion."""
        choices = getattr(response, "choices", None) or []
        if not choices:
            raise ModelError(f"{self._role.model} returned no choices", retryable=False)
        message = getattr(choices[0], "message", None)
        text = getattr(message, "content", "") or ""
        return Completion(text=text, tool_calls=tool_calls_of(message), usage=usage_of(response))

    def _failure(self, ctx: RequestContext, exc: Exception) -> ModelError:
        """A provider exception as a ModelError, with the credential scrubbed out of it."""
        error = provider_error(self._role.model, exc, self._role.api_key.get_secret_value())
        self._trace.event(
            ctx,
            "model_error",
            {
                "model": self._role.model,
                "retryable": error.retryable,
                "error": str(error),
            },
        )
        return error
