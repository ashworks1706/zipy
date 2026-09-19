"""Settings of the drive tool, and the file shape its document feed works in.

The actions are the MCP server's. What remains here is the ingestion feed.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from engine.tools.remote import RemoteSettings


class DriveSettings(RemoteSettings):
    """[tools.drive] settings an org may override."""

    sync_hours: int = 12


class File(BaseModel):
    """One Drive file or folder, as the document feed reads it."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    mime_type: str
    link: str
    modified_at: datetime
