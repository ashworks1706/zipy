"""The Zoom API over httpx. Also downloads transcripts for ingestion."""

from __future__ import annotations

from engine.core.types import ProviderAuth
from engine.tools.zoom.schemas import (
    LatestSummaryParams,
    ListRecordingsParams,
    RecordingList,
    Transcript,
    ZoomSettings,
)


class ZoomClient:
    """Calls Zoom with the org's credential."""

    def __init__(self, auth: ProviderAuth, settings: ZoomSettings) -> None:
        self._auth = auth
        self._settings = settings

    async def list_recordings(self, params: ListRecordingsParams) -> RecordingList:
        """Cloud recordings since the date."""
        raise NotImplementedError

    async def latest_summary(self, params: LatestSummaryParams) -> Transcript:
        """The newest recording's transcript."""
        raise NotImplementedError

    async def transcript(self, meeting_id: str) -> Transcript:
        """One recording's transcript, as the ingestion worker downloads it."""
        raise NotImplementedError
