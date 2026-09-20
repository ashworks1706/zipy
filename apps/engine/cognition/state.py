"""What is held about one person, and the one path that changes it.

Everything that reads or writes collaboration state goes through here, so the switch is checked
in one place and every write carries where it came from. A state that moved always has the
observations that moved it.
"""

from __future__ import annotations

from collections.abc import Sequence

from engine.cognition import signals as reading
from engine.cognition.conditioning import render
from engine.core.config import Collaboration
from engine.core.protocols import CollaborationStore
from engine.core.types import (
    ChatMessage,
    CollaborationState,
    Conditioning,
    Provenance,
    RequestContext,
    Signal,
)


class Cognition:
    """Reads a turn into signals, holds them, and renders what they ask for."""

    def __init__(
        self,
        store: CollaborationStore,
        settings: Collaboration,
        conditioning: Conditioning = Conditioning.TEXT,
        model: str = "",
    ) -> None:
        self._store = store
        self._settings = settings
        self._conditioning = conditioning
        self._model = model

    @property
    def enabled(self) -> bool:
        """Whether any of this runs. Off means every prompt is what it would be without it."""
        return self._settings.enabled

    def read(self, message: str, history: Sequence[ChatMessage]) -> list[Signal]:
        """What a follow-up turn shows. Empty for a turn that follows no answer."""
        if not self._settings.enabled:
            return []
        return reading.read(
            message,
            list(history),
            self._settings.brevity_triggers,
            self._settings.detail_triggers,
            self._settings.correction_triggers,
        )

    async def state(self, ctx: RequestContext) -> CollaborationState:
        """What is held about the asker."""
        return await self._store.state(ctx.org_id, ctx.member)

    async def conditioning(self, ctx: RequestContext) -> str:
        """What the asker's state asks for, or nothing while this is off."""
        if not self._settings.enabled:
            return ""
        state = await self.state(ctx)
        return render(state, self._settings.min_observations, self._conditioning)

    async def observe(self, ctx: RequestContext, signals: Sequence[Signal]) -> None:
        """Record what a turn showed about the asker, with the run that showed it."""
        if not self._settings.enabled or not signals:
            return
        await self._store.observe(ctx.org_id, ctx.member, signals, self.provenance(ctx))

    def provenance(self, ctx: RequestContext) -> Provenance:
        """Which request, which variant and which model an observation came from."""
        return Provenance(request_id=ctx.request_id, arm=self._settings.arm, model=self._model)
