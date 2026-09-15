"""The Zoom API over httpx. Also downloads transcripts for ingestion."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx

from engine.core.types import CredentialError, Document, ProviderAuth, ToolError, ZipyError
from engine.tools.zoom.schemas import (
    LatestSummaryParams,
    ListRecordingsParams,
    Recording,
    RecordingList,
    Transcript,
    ZoomSettings,
)

API = "https://api.zoom.us/v2"
TIMEOUT_SECS = 30.0
PAGE_SIZE = 30
WINDOW_DAYS = 30
LOOKBACK_DAYS = 90
SOURCE = "zoom"
TRANSCRIPT = "TRANSCRIPT"


def _utc(value: datetime) -> datetime:
    """The time as an aware UTC time. A naive time is read as UTC."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _started(raw: str) -> datetime:
    """When a recording started, as an aware UTC time."""
    return _utc(datetime.fromisoformat(raw)) if raw else datetime.now(UTC)


def _meeting_uuid(raw: str) -> str:
    """A meeting uuid in the path. One holding a slash is escaped twice."""
    once = quote(raw, safe="")
    return quote(once, safe="") if raw.startswith("/") or "//" in raw else once


def _recording(raw: dict[str, Any]) -> Recording:
    """One cloud recording as the model sees it."""
    files = raw.get("recording_files") or []
    return Recording(
        meeting_id=str(raw.get("uuid") or raw.get("id") or ""),
        topic=str(raw.get("topic", "")),
        start=_started(str(raw.get("start_time", ""))),
        has_transcript=any(f.get("file_type") == TRANSCRIPT for f in files),
    )


def _vtt(body: str) -> str:
    """The spoken text of a WebVTT transcript, one cue per line."""
    lines = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line == "WEBVTT" or "-->" in line or line.isdigit():
            continue
        if line.startswith(("NOTE", "STYLE", "REGION")):
            continue
        lines.append(line)
    return "\n".join(lines)


def _failed(action: str, response: httpx.Response) -> ZipyError:
    """The error the model reads. Carries the status and Zoom's message, never the token."""
    message = ""
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        message = str(body.get("message", ""))
    detail = f": {message}" if message else ""
    if response.status_code == 401:
        return CredentialError(f"the Zoom credential is expired or revoked{detail}")
    return ToolError(f"Zoom refused {action} with status {response.status_code}{detail}")


class ZoomClient:
    """Calls Zoom with the org's credential."""

    def __init__(
        self,
        auth: ProviderAuth,
        settings: ZoomSettings,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._auth = auth
        self._settings = settings
        self._transport = transport

    async def list_recordings(self, params: ListRecordingsParams) -> RecordingList:
        """Cloud recordings since the date."""
        meetings = await self._meetings("list_recordings", _utc(params.since), datetime.now(UTC))
        recordings = [_recording(meeting) for meeting in meetings]
        recordings.sort(key=lambda r: r.start, reverse=True)
        return RecordingList(recordings=recordings)

    async def latest_summary(self, params: LatestSummaryParams) -> Transcript:
        """The newest recording's transcript."""
        now = datetime.now(UTC)
        meetings = await self._meetings("latest_summary", now - timedelta(days=LOOKBACK_DAYS), now)
        wanted = params.topic.casefold()
        matching = [
            recording
            for recording in (_recording(meeting) for meeting in meetings)
            if recording.has_transcript and wanted in recording.topic.casefold()
        ]
        if not matching:
            named = f" about {params.topic}" if params.topic else ""
            raise ToolError(f"no Zoom recording{named} has a transcript yet")
        newest = max(matching, key=lambda r: r.start)
        return await self.transcript(newest.meeting_id)

    async def transcript(self, meeting_id: str) -> Transcript:
        """One recording's transcript, as the ingestion worker downloads it."""
        raw = await self._get(
            "transcript", f"{API}/meetings/{_meeting_uuid(meeting_id)}/recordings"
        )
        recording = _recording(raw)
        for entry in raw.get("recording_files") or []:
            if entry.get("file_type") == TRANSCRIPT and entry.get("download_url"):
                body = await self._download(str(entry["download_url"]))
                return Transcript(recording=recording, text=_vtt(body))
        raise ToolError(f"the Zoom recording {meeting_id} has no transcript")

    async def documents(
        self, since: datetime | None, source_id: str = ""
    ) -> AsyncIterator[Document]:
        """Transcripts recorded since the time, or the one named by source_id."""
        if source_id:
            yield _document(await self.transcript(source_id))
            return
        now = datetime.now(UTC)
        start = _utc(since) if since is not None else now - timedelta(days=WINDOW_DAYS)
        for meeting in await self._meetings("documents", start, now):
            recording = _recording(meeting)
            if recording.has_transcript:
                yield _document(await self.transcript(recording.meeting_id))

    async def _meetings(
        self, action: str, since: datetime, until: datetime
    ) -> list[dict[str, Any]]:
        """Every recorded meeting in the window. Zoom only answers a month at a time."""
        meetings: list[dict[str, Any]] = []
        window_start = since
        while window_start < until:
            window_end = min(window_start + timedelta(days=WINDOW_DAYS), until)
            token = ""
            while True:
                query: dict[str, str] = {
                    "from": window_start.date().isoformat(),
                    "to": window_end.date().isoformat(),
                    "page_size": str(PAGE_SIZE),
                }
                if token:
                    query["next_page_token"] = token
                raw = await self._get(action, f"{API}/users/me/recordings", query)
                meetings.extend(raw.get("meetings") or [])
                token = str(raw.get("next_page_token") or "")
                if not token:
                    break
            window_start = window_end + timedelta(days=1)
        return meetings

    async def _get(
        self, action: str, url: str, query: dict[str, str] | None = None
    ) -> dict[str, Any]:
        """One Zoom request returning JSON."""
        response = await self._send(action, url, query)
        try:
            body = response.json()
        except ValueError as exc:
            raise ToolError(f"Zoom answered {action} with something that is not JSON") from exc
        if not isinstance(body, dict):
            raise ToolError(f"Zoom answered {action} with something that is not an object")
        return body

    async def _download(self, url: str) -> str:
        """One recording file, as text."""
        return (await self._send("transcript", url, None)).text

    async def _send(self, action: str, url: str, query: dict[str, str] | None) -> httpx.Response:
        """One authorized request. A failure never carries the url or the token."""
        headers = {
            "Authorization": f"Bearer {self._auth.access_token.get_secret_value()}",
            "Accept": "application/json",
        }
        try:
            async with httpx.AsyncClient(
                timeout=TIMEOUT_SECS, transport=self._transport, follow_redirects=True
            ) as client:
                response = await client.get(url, params=query, headers=headers)
        except httpx.HTTPError as exc:
            raise ToolError(f"Zoom did not answer {action}: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            raise _failed(action, response)
        return response


def _document(transcript: Transcript) -> Document:
    """One transcript as a searchable document."""
    return Document(
        source=SOURCE,
        source_id=transcript.recording.meeting_id,
        title=transcript.recording.topic,
        text=transcript.text,
        updated_at=transcript.recording.start,
        metadata={"topic": transcript.recording.topic},
    )
