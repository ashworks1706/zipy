"""Params, results and settings of the zoom tool."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ZoomSettings(_Model):
    """[tools.zoom] settings an org may override. Transcripts arrive by webhook, not by sync."""


class Recording(_Model):
    """One cloud recording."""

    meeting_id: str
    topic: str
    start: datetime
    has_transcript: bool


class ListRecordingsParams(_Model):
    """Recordings since a date."""

    since: datetime


class RecordingList(_Model):
    """Recordings, newest first."""

    recordings: list[Recording]


class LatestSummaryParams(_Model):
    """The newest recording, optionally matching a topic."""

    topic: str = ""


class Transcript(_Model):
    """A recording and its transcript text, for the model to summarize."""

    recording: Recording
    text: str
