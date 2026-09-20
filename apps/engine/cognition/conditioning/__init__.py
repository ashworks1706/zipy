"""One renderer per conditioning: how a state reaches the model.

The endpoint decides which is possible. Text works against every OpenAI-compatible server, hosted
or local. A prefix in embedding space goes here when there is a server under it that accepts one,
and nothing above this package changes.
"""

from collections.abc import Callable

from engine.cognition.conditioning.text import render_text
from engine.core.types import CollaborationState, Conditioning

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


__all__ = ["RENDERERS", "render"]
