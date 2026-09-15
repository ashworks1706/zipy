"""Slack rendering: Block Kit sections, and actions blocks for a ConfirmPrompt."""

from __future__ import annotations

from typing import Any

from engine.gateway.messages import Answer, ConfirmPrompt

CONFIRM_ACTION = "zipy_confirm"
CANCEL_ACTION = "zipy_cancel"
ACTIONS: dict[str, Answer] = {CONFIRM_ACTION: Answer.CONFIRM, CANCEL_ACTION: Answer.CANCEL}


def text_blocks(text: str) -> list[dict[str, Any]]:
    """One mrkdwn section holding a reply."""
    return [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]


def confirm_blocks(prompt: ConfirmPrompt) -> list[dict[str, Any]]:
    """The blocks describing the pending call, with confirm and cancel buttons."""
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": prompt.summary}},
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"expires {prompt.expires_at.isoformat(timespec='seconds')}",
                }
            ],
        },
        {
            "type": "actions",
            "block_id": prompt.confirmation_id,
            "elements": [
                {
                    "type": "button",
                    "action_id": CONFIRM_ACTION,
                    "style": "danger",
                    "value": prompt.confirmation_id,
                    "text": {"type": "plain_text", "text": "Confirm"},
                },
                {
                    "type": "button",
                    "action_id": CANCEL_ACTION,
                    "value": prompt.confirmation_id,
                    "text": {"type": "plain_text", "text": "Cancel"},
                },
            ],
        },
    ]
