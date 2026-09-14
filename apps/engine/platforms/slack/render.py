"""Slack rendering: Block Kit sections, and actions blocks for a ConfirmPrompt."""

from __future__ import annotations

from typing import Any

from engine.gateway.messages import ConfirmPrompt


def confirm_blocks(prompt: ConfirmPrompt) -> list[dict[str, Any]]:
    """The blocks describing the pending call, with confirm and cancel buttons."""
    raise NotImplementedError
