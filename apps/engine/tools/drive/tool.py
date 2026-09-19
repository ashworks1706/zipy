"""The drive tool, run on the Google Drive MCP server."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel

from engine.core.types import Document, ProviderAuth
from engine.tools.base import Action, require_auth
from engine.tools.drive.client import DriveClient
from engine.tools.drive.schemas import DriveSettings
from engine.tools.remote import Catalog, RemoteTool, actions_from, load_catalog

CATALOG = load_catalog(__file__)


class DriveTool(RemoteTool[DriveSettings]):
    """Google Drive for the org's shared drive.

    The actions run on the MCP server. The document feed stays on the Drive API, which is the only
    one of the two that can say what changed since a time.
    """

    name: ClassVar[str] = "drive"
    provider: ClassVar[str] = "google"
    owns: ClassVar[tuple[str, ...]] = ("googleapiclient",)
    syncs: ClassVar[bool] = True
    settings_model: ClassVar[type[BaseModel]] = DriveSettings
    catalog: ClassVar[Catalog] = CATALOG
    actions: ClassVar[Mapping[str, Action]] = actions_from(CATALOG, "drive")

    def documents(
        self, auth: ProviderAuth | None, since: datetime | None, source_id: str = ""
    ) -> AsyncIterator[Document]:
        """Documents changed since the time, or the one named by source_id."""
        client = DriveClient(require_auth(auth, self.provider), self.settings)
        return client.documents(since, source_id)
