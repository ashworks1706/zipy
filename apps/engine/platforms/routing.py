"""When a message is one Zipy answers, and where the answer lives.

A thread is the conversation. Inside one, only a reply to something Zipy said continues it, so
people talk in the thread without Zipy answering every line. Outside a thread, addressing Zipy
opens one. A direct message needs neither. Every threaded platform shares these rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

#: Longest thread name the platforms accept, in characters.
THREAD_NAME_MAX = 100

#: Thread name used when the message carries no words.
THREAD_NAME_FALLBACK = "Question"


class Trigger(StrEnum):
    """Why Zipy answers a message."""

    DIRECT = "direct"
    OPENING = "opening"
    REPLY = "reply"


@dataclass(frozen=True)
class Arrival:
    """Where one message arrived and how it addresses Zipy."""

    direct: bool = False
    in_thread: bool = False
    mentions_bot: bool = False
    replies_to_bot: bool = False


def trigger(arrival: Arrival) -> Trigger | None:
    """Why Zipy answers this message, or None when the message is not for it."""
    if arrival.direct:
        return Trigger.DIRECT
    if arrival.in_thread:
        return Trigger.REPLY if arrival.replies_to_bot else None
    if arrival.mentions_bot or arrival.replies_to_bot:
        return Trigger.OPENING
    return None


def quoted_reply(author_id: str | None, content: str, me: str) -> str:
    """The text of the message a reply answers, when Zipy wrote it and it holds text.

    A reply to a person, or to another bot, is not a turn: the thread belongs to everyone in it.
    """
    if author_id is None or author_id != me:
        return ""
    return content.strip()


def thread_name(text: str) -> str:
    """A thread name for a message: one line, within the limit, never empty."""
    line = " ".join(text.split())
    if not line:
        return THREAD_NAME_FALLBACK
    if len(line) <= THREAD_NAME_MAX:
        return line
    return line[: THREAD_NAME_MAX - 3].rstrip() + "..."
