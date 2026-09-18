"""Collaboration state as the thing that conditions the model.

Scores are rendered as the behaviour they ask for, not as numbers: a model reads an instruction
better than it reads 0.82, and a person reading their own state sees what it changes.

One renderer per Conditioning. Text is the only one built: it works against every
OpenAI-compatible endpoint, hosted or local. A prefix in embedding space goes here too when
there is a server under it that accepts one, and nothing above this module changes.
"""

from __future__ import annotations

from collections.abc import Callable

from engine.core.types import CollaborationState, Conditioning, Dimension

#: How far from neutral a score must be before it says anything.
BAND = 0.15

#: What each end of each dimension asks for.
WORDING: dict[Dimension, tuple[str, str]] = {
    Dimension.DEPTH: (
        "Answer briefly. Lead with the result and leave out the reasoning unless asked.",
        "Explain your reasoning and what you checked, not only the result.",
    ),
    Dimension.AUTONOMY: (
        "Ask before anything beyond a plain read, even when you could work it out.",
        "Act on what you are confident about, and ask only when a choice is genuinely open.",
    ),
    Dimension.FORMALITY: (
        "Keep the wording plain and direct.",
        "Keep the wording formal.",
    ),
}


def render_text(state: CollaborationState, min_observations: int) -> str:
    """The lines this state asks for. Empty until enough has been observed to mean anything."""
    if state.observations < min_observations:
        return ""
    lines = []
    for dimension, (low, high) in WORDING.items():
        score = state.score(dimension)
        if score <= 0.5 - BAND:
            lines.append(f"- {low}")
        elif score >= 0.5 + BAND:
            lines.append(f"- {high}")
    return "\n".join(lines)


#: One renderer per conditioning. core/types/collaboration.IMPLEMENTED names which exist.
RENDERERS: dict[Conditioning, Callable[[CollaborationState, int], str]] = {
    Conditioning.TEXT: render_text,
}


def render(
    state: CollaborationState,
    min_observations: int,
    conditioning: Conditioning = Conditioning.TEXT,
) -> str:
    """What this state conditions the model with. A conditioning with no renderer is a KeyError.

    Config rejects an unbuilt conditioning at boot, so the lookup cannot fail on a running engine.
    """
    return RENDERERS[conditioning](state, min_observations)
