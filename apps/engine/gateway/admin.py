"""The admin commands: setup, connect, enable, disable, config, remember, forget, status.

These are parsed from the message text and run without the model, identically on every platform.
setup and connect answer privately, because they carry OAuth links.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Verb(StrEnum):
    """An admin command."""

    SETUP = "setup"
    CONNECT = "connect"
    ENABLE = "enable"
    DISABLE = "disable"
    CONFIG = "config"
    REMEMBER = "remember"
    FORGET = "forget"
    STATUS = "status"


@dataclass(frozen=True)
class AdminCommand:
    """A parsed admin command and its arguments."""

    verb: Verb
    args: tuple[str, ...]


def parse(text: str) -> AdminCommand | None:
    """The admin command a message starts with, or None for a request to the agent."""
    words = text.split()
    if not words or words[0].lower() not in Verb:
        return None
    return AdminCommand(Verb(words[0].lower()), tuple(words[1:]))
