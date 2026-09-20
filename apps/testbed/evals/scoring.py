"""What a run is scored on, in two axes that are never added together.

Correctness is whether the run did the right thing: the calls it made, the facts the answer
carries, whether a destructive call waited. Behaviour is how it did it: how long the answer is,
whether it asked rather than acted, which tool it reached for first. Correctness is a pass or a
fail. Behaviour is measured, not judged, because there is no right answer to it: it is what the
contrast between two collaboration states is read from.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from engine.core.types import AuditEntry
from testbed.evals.cases import Case

#: What reads as the run asking rather than answering.
ASKING = ("?",)


@dataclass(frozen=True)
class Correctness:
    """Every check one run either passed or failed."""

    calls: bool
    contains: bool
    confirmed: bool

    @property
    def passed(self) -> bool:
        """Whether the run got everything right."""
        return self.calls and self.contains and self.confirmed

    def failures(self) -> list[str]:
        """The names of the checks that failed."""
        return [
            name
            for name, ok in (
                ("calls", self.calls),
                ("contains", self.contains),
                ("confirmed", self.confirmed),
            )
            if not ok
        ]


@dataclass(frozen=True)
class Behaviour:
    """How the run answered, as numbers rather than judgments."""

    words: int
    asked: bool
    first_call: str
    calls: int


def correctness(case: Case, answer: str, made: Sequence[str], confirmed: bool) -> Correctness:
    """The three checks, each read from what the run actually did."""
    lowered = answer.lower()
    return Correctness(
        calls=set(case.calls) <= set(made),
        contains=all(text.lower() in lowered for text in case.contains),
        confirmed=confirmed == case.confirms,
    )


def behaviour(answer: str, entries: Sequence[AuditEntry]) -> Behaviour:
    """The measurements, taken from the answer and the calls the run logged."""
    return Behaviour(
        words=len(answer.split()),
        asked=any(mark in answer for mark in ASKING),
        first_call=entries[0].action if entries else "",
        calls=len(entries),
    )


def moved(low: Behaviour, high: Behaviour) -> bool:
    """Whether two runs of one case behaved differently at all."""
    return (low.words, low.asked, low.first_call, low.calls) != (
        high.words,
        high.asked,
        high.first_call,
        high.calls,
    )
