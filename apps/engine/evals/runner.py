"""Running the cases, and running a case twice to read the contrast.

One run is one message through the gateway, and the confirmation it may come back with. What the
run did is read from the audit log, which the executor writes whether or not the model tells the
truth about what it called.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from engine.core.types import CollaborationState, Dimension, Evidence, Signal, ZipyError
from engine.core.types.collaboration import apply_signals
from engine.evals.cases import Case, Contrast, Suite
from engine.evals.scoring import (
    Behaviour,
    Correctness,
    behaviour,
    correctness,
    moved,
)
from engine.evals.stack import SURFACE, Stack
from engine.gateway.messages import Answer, ConfirmPrompt, Inbound, InboundAnswer, Text

#: How far a contrast pushes a dimension, which is as far as it goes.
ENDS = (0.0, 1.0)

#: Enough observations that the state renders whatever min_observations is set to.
PUSHES = 20


@dataclass(frozen=True)
class Run:
    """What one case did, and what it scored."""

    case: str
    answer: str
    calls: tuple[str, ...]
    correctness: Correctness
    behaviour: Behaviour
    error: str = ""


@dataclass(frozen=True)
class Pair:
    """One case run at both ends of one dimension."""

    case: str
    dimension: Dimension
    low: Run
    high: Run

    @property
    def held(self) -> bool:
        """Whether correctness survived the change of state, which it must."""
        return self.low.correctness.passed == self.high.correctness.passed

    @property
    def moved(self) -> bool:
        """Whether behaviour changed at all, which is what the state is for."""
        return moved(self.low.behaviour, self.high.behaviour)


def _text(replies: list[Text | ConfirmPrompt]) -> str:
    """Every text reply as one answer, ignoring the confirmation prompts."""
    return "\n".join(reply.text for reply in replies if isinstance(reply, Text))


async def once(stack: Stack, case: Case) -> Run:
    """One case through the gateway, answering a confirmation when the run asks for one."""
    stack.audit.entries.clear()
    now = datetime.now(UTC)
    event = Inbound(
        channel=stack.channel,
        member=stack.member,
        display_name="Officer",
        text=case.ask,
        direct=False,
        received_at=now,
    )
    try:
        replies = await stack.gateway.message(event, SURFACE)
        prompts = [reply for reply in replies if isinstance(reply, ConfirmPrompt)]
        answered = _text(replies)
        for prompt in prompts:
            answer = Answer.CONFIRM if case.approve else Answer.CANCEL
            resumed = await stack.gateway.answer(
                InboundAnswer(
                    channel=stack.channel,
                    member=stack.member,
                    confirmation_id=prompt.confirmation_id,
                    answer=answer,
                    received_at=datetime.now(UTC),
                ),
                SURFACE,
            )
            answered = f"{answered}\n{_text(resumed)}".strip()
    except ZipyError as exc:
        return Run(
            case=case.id,
            answer="",
            calls=(),
            correctness=Correctness(False, False, False),
            behaviour=Behaviour(0, False, "", 0),
            error=f"{type(exc).__name__}: {exc}",
        )
    entries = list(stack.audit.entries)
    made = tuple(entry.action for entry in entries)
    return Run(
        case=case.id,
        answer=answered,
        calls=made,
        correctness=correctness(case, answered, made, bool(prompts)),
        behaviour=behaviour(answered, entries),
    )


def _push(stack: Stack, dimension: Dimension, target: float) -> None:
    """Put the member's state at one end of one dimension, without going through a turn."""
    state = CollaborationState(member=stack.member)
    signals = [Signal(dimension, target, Evidence.STATED_PREFERENCE)] * PUSHES
    stack.collaboration.by_member[(stack.org_id, stack.member)] = apply_signals(state, signals)


async def pair(stack: Stack, suite: Suite, contrast: Contrast) -> Pair:
    """One case run at both ends of one dimension, with everything else held still."""
    case = suite.by_id[contrast.case]
    runs = []
    for target in ENDS:
        _push(stack, contrast.dimension, target)
        runs.append(await once(stack, case))
    stack.collaboration.by_member.clear()
    return Pair(case=case.id, dimension=contrast.dimension, low=runs[0], high=runs[1])


async def run(stack: Stack, suite: Suite) -> tuple[list[Run], list[Pair]]:
    """Every case, then every contrast."""
    runs = [await once(stack, case) for case in suite.cases]
    pairs = [await pair(stack, suite, contrast) for contrast in suite.contrasts]
    return runs, pairs
