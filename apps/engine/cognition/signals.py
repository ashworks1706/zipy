"""What the wording of a follow-up turn shows about how someone wants to be worked with.

Only a turn that follows an answer counts. Asking "why" as an opening question is a question;
asking it straight after an answer is a request for more than the answer gave.

A trigger decides which category a turn falls in, and the category is all that is kept. The
message itself is read and discarded, exactly as the confirmation signals are.
"""

from __future__ import annotations

from collections.abc import Sequence

from engine.core.types import ChatMessage, Dimension, Evidence, Signal, Speaker

#: How far a read turn moves its dimension, against a stated preference at STATED_WEIGHT.
WEIGHT = 1.5

#: What each category asks for: the dimension it moves and the end it moves toward.
MEANS: dict[Evidence, tuple[Dimension, float]] = {
    Evidence.ASKED_FOR_BREVITY: (Dimension.DEPTH, 0.0),
    Evidence.ASKED_FOR_DETAIL: (Dimension.DEPTH, 1.0),
    Evidence.CORRECTED: (Dimension.AUTONOMY, 0.0),
}


def follows_an_answer(history: Sequence[ChatMessage]) -> bool:
    """Whether Zipy answered just before this turn.

    Trailing user turns are skipped, because a platform may or may not have the turn being handled
    in the history it hands back. Skipping them reads the same either way.
    """
    for message in reversed(history):
        if message.speaker is Speaker.USER:
            continue
        return message.speaker is Speaker.ASSISTANT
    return False


def _hit(text: str, triggers: Sequence[str]) -> bool:
    """Whether a normalised message holds one of the trigger phrases."""
    return any(trigger.lower() in text for trigger in triggers)


def read(
    message: str,
    history: Sequence[ChatMessage],
    brevity: Sequence[str],
    detail: Sequence[str],
    correction: Sequence[str],
) -> list[Signal]:
    """The signals one turn raises. Empty unless it follows an answer and hits a trigger.

    A turn that reads as a correction raises only that: it says the answer was wrong, which is
    about acting without asking, not about length.
    """
    if not follows_an_answer(history):
        return []
    text = " ".join(message.lower().split())
    found: list[Evidence] = []
    if _hit(text, correction):
        found.append(Evidence.CORRECTED)
    else:
        if _hit(text, brevity):
            found.append(Evidence.ASKED_FOR_BREVITY)
        if _hit(text, detail):
            found.append(Evidence.ASKED_FOR_DETAIL)
    if len(found) > 1:
        return []
    return [
        Signal(dimension=MEANS[e][0], target=MEANS[e][1], evidence=e, weight=WEIGHT) for e in found
    ]
