"""The message array for one model call.

The system prompt comes from a Jinja2 template with the org name, the user and role, and the org
facts. Recalled chunks go in a second system message labelled RELEVANT PAST CONTEXT. Raw API
responses only ever appear as tool messages, never in a system message.
"""

from __future__ import annotations

from collections.abc import Sequence

from engine.core.types import ChatMessage, Org, RequestContext, ToolOutcome
from engine.memory.manager import Context


class PromptBuilder:
    """Renders the system template and assembles messages."""

    def __init__(self, template: str) -> None:
        self._template = template

    def build(
        self,
        ctx: RequestContext,
        org: Org,
        markup: str,
        context: Context,
        message: str,
        outcomes: Sequence[ToolOutcome] = (),
    ) -> list[ChatMessage]:
        """System prompt, recalled context if any, history, the message, then tool results.

        markup names the formatting the platform renders, such as discord-markdown or slack-mrkdwn.
        """
        raise NotImplementedError
