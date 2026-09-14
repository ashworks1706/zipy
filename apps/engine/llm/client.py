"""The ChatModel over LiteLLM, for one [models.*] role. Spend comes back in Usage."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from engine.core.config import ModelRole
from engine.core.protocols import TraceSink
from engine.core.types import ChatMessage, Completion, RequestContext


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
        raise NotImplementedError
