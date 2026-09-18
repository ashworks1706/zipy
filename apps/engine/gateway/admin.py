"""The commands: setup, connect, enable, disable, config, remember, forget, status, prefer.

These are parsed from the message text and run without the model, identically on every platform.
setup and connect answer privately, because they carry OAuth links. Every one but status and
prefer changes the org, so an admin runs it; status and prefer read and write only the caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Verb(StrEnum):
    """A command parsed from the message text."""

    SETUP = "setup"
    CONNECT = "connect"
    ENABLE = "enable"
    DISABLE = "disable"
    CONFIG = "config"
    REMEMBER = "remember"
    FORGET = "forget"
    STATUS = "status"
    PREFER = "prefer"


@dataclass(frozen=True)
class AdminCommand:
    """A parsed command and its arguments."""

    verb: Verb
    args: tuple[str, ...]


def parse(text: str) -> AdminCommand | None:
    """The command a message starts with, or None for a request to the agent."""
    words = text.split()
    if not words or words[0].lower() not in Verb:
        return None
    return AdminCommand(Verb(words[0].lower()), tuple(words[1:]))
