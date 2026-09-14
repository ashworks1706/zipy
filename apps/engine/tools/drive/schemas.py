"""Params, results and settings of the drive tool."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DriveSettings(_Model):
    """[tools.drive] settings an org may override."""

    sync_hours: int = 12

    max_results: int = 10


class File(_Model):
    """One Drive file or folder."""

    id: str
    name: str
    mime_type: str
    link: str
    modified_at: datetime


class SearchFilesParams(_Model):
    """Files whose name or content matches a query."""

    query: str


class ListFolderParams(_Model):
    """The contents of a folder, by name or id."""

    folder: str


class FileList(_Model):
    """Files, most recently modified first."""

    files: list[File]
