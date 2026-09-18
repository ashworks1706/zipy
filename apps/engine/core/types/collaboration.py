"""How one person works with the agent, as scored dimensions. No conversation text, ever.

A signal carries a dimension, a target and the kind of evidence behind it. It carries no quote,
no summary and no free text, so the state cannot come to hold what was said.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from engine.core.types.identity import MemberRef

#: The value every dimension starts at, and the middle of its range.
NEUTRAL = 0.5

#: Weight of one observation when the caller names none.
DEFAULT_ALPHA = 0.15

#: How many ordinary observations a stated preference counts for.
STATED_WEIGHT = 4.0


class Dimension(StrEnum):
    """What is scored about a person. A new one needs no migration."""

    #: How much explanation an answer carries.
    DEPTH = "depth"
    #: How readily the agent acts rather than asking first.
    AUTONOMY = "autonomy"
    #: How formal the wording is.
    FORMALITY = "formality"


class Conditioning(StrEnum):
    """How a person's state reaches the model.

    The endpoint decides which is possible. Every OpenAI-compatible server takes tokens, so text
    works everywhere; a prefix in embedding space needs a server that accepts input embeddings.
    """

    #: Lines in the system prompt. Hosted providers, llama.cpp, vLLM.
    TEXT = "text"
    #: An embedding prefix conditioning the model below the text. vLLM and SGLang only.
    PREFIX = "prefix"


#: The conditionings a renderer exists for. test_memory.py holds the renderers to this.
IMPLEMENTED: tuple[Conditioning, ...] = (Conditioning.TEXT,)


class Evidence(StrEnum):
    """Why a signal was raised. A category, never the text it came from."""

    CONFIRMATION_CONFIRMED = "confirmation_confirmed"
    CONFIRMATION_CANCELLED = "confirmation_cancelled"
    STATED_PREFERENCE = "stated_preference"
    #: A turn right after an answer asking for it shorter.
    ASKED_FOR_BREVITY = "asked_for_brevity"
    #: A turn right after an answer asking for more of it.
    ASKED_FOR_DETAIL = "asked_for_detail"
    #: A turn right after an answer saying it got something wrong.
    CORRECTED = "corrected"


@dataclass(frozen=True)
class Signal:
    """One observation moving one dimension toward a target."""

    dimension: Dimension
    target: float
    evidence: Evidence
    #: How many ordinary observations this one counts for.
    weight: float = 1.0


@dataclass(frozen=True)
class CollaborationState:
    """A person's scores, and how many observations are behind them."""

    member: MemberRef
    scores: Mapping[Dimension, float] = field(default_factory=dict)
    observations: int = 0
    updated_at: datetime | None = None

    def score(self, dimension: Dimension) -> float:
        """The score of one dimension, neutral until something has been observed."""
        return self.scores.get(dimension, NEUTRAL)


def apply_signals(
    state: CollaborationState, signals: Sequence[Signal], alpha: float = DEFAULT_ALPHA
) -> CollaborationState:
    """The state after signals, each moving its dimension toward the target by alpha.

    A moving average, so one observation never decides a dimension and old ones fade. A signal
    weighing more than one moves further, up to landing on its target.
    """
    if not signals:
        return state
    scores = dict(state.scores)
    for signal in signals:
        current = scores.get(signal.dimension, NEUTRAL)
        step = min(alpha * signal.weight, 1.0)
        scores[signal.dimension] = (1.0 - step) * current + step * signal.target
    return CollaborationState(
        member=state.member,
        scores=scores,
        observations=state.observations + len(signals),
        updated_at=datetime.now(UTC),
    )
