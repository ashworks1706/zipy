"""Discord rendering: an embed with confirm and cancel buttons for a ConfirmPrompt."""

from __future__ import annotations

import discord

from engine.gateway.messages import ConfirmPrompt


def confirm_embed(prompt: ConfirmPrompt) -> discord.Embed:
    """The embed describing the pending call."""
    raise NotImplementedError
