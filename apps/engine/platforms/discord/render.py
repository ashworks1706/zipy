"""Discord rendering: an embed with confirm and cancel buttons for a ConfirmPrompt."""

from __future__ import annotations

import discord

from engine.gateway.messages import Answer, ConfirmPrompt

PREFIX = "zipy:confirm"


def custom_id(confirmation_id: str, answer: Answer) -> str:
    """The button id carrying the confirmation it answers and the answer."""
    return f"{PREFIX}:{confirmation_id}:{answer.value}"


def parse_custom_id(value: str) -> tuple[str, Answer] | None:
    """The confirmation and the answer a button id carries, or None when it is not Zipy's."""
    if not value.startswith(f"{PREFIX}:"):
        return None
    confirmation_id, separator, answer = value[len(PREFIX) + 1 :].rpartition(":")
    if not separator or not confirmation_id or answer not in tuple(Answer):
        return None
    return confirmation_id, Answer(answer)


def confirm_embed(prompt: ConfirmPrompt) -> discord.Embed:
    """The embed describing the pending call."""
    embed = discord.Embed(
        title="Confirm",
        description=prompt.summary,
        colour=discord.Colour.orange(),
    )
    embed.set_footer(text=f"expires {prompt.expires_at.isoformat(timespec='seconds')}")
    return embed


def confirm_view(prompt: ConfirmPrompt) -> discord.ui.View:
    """Confirm and cancel buttons, each carrying the confirmation id."""
    view: discord.ui.View = discord.ui.View(timeout=None)
    view.add_item(
        discord.ui.Button(
            label="Confirm",
            style=discord.ButtonStyle.danger,
            custom_id=custom_id(prompt.confirmation_id, Answer.CONFIRM),
        )
    )
    view.add_item(
        discord.ui.Button(
            label="Cancel",
            style=discord.ButtonStyle.secondary,
            custom_id=custom_id(prompt.confirmation_id, Answer.CANCEL),
        )
    )
    return view
