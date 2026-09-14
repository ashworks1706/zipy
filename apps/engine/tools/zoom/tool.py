"""The zoom tool."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from datetime import datetime
from typing import Any, ClassVar

from pydantic import BaseModel

from engine.core.types import Document, ProviderAuth
from engine.tools.base import Action, BaseTool, require_auth
from engine.tools.zoom import schemas as s
from engine.tools.zoom.client import ZoomClient


class ZoomTool(BaseTool[s.ZoomSettings]):
    """Zoom recordings for the org's account."""

    name: ClassVar[str] = "zoom"
    provider: ClassVar[str] = "zoom"
    owns: ClassVar[tuple[str, ...]] = ()
    syncs: ClassVar[bool] = True
    settings_model: ClassVar[type[BaseModel]] = s.ZoomSettings
    actions: ClassVar[Mapping[str, Action]] = {
        "list_recordings": Action(
            "List cloud recordings since a date.", s.ListRecordingsParams, s.RecordingList
        ),
        "latest_summary": Action(
            "Fetch the newest meeting transcript to summarize.",
            s.LatestSummaryParams,
            s.Transcript,
        ),
    }

    async def execute(self, action: str, params: BaseModel, auth: ProviderAuth | None) -> BaseModel:
        client = ZoomClient(require_auth(auth, self.provider), self.settings)
        handlers: dict[str, Callable[[Any], Awaitable[BaseModel]]] = {
            "list_recordings": client.list_recordings,
            "latest_summary": client.latest_summary,
        }
        return await handlers[action](params)

    def documents(
        self, auth: ProviderAuth | None, since: datetime | None, source_id: str = ""
    ) -> AsyncIterator[Document]:
        """Documents changed since the time, or the one named by source_id."""
        raise NotImplementedError
