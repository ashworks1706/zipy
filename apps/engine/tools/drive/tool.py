"""The drive tool."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from datetime import datetime
from typing import Any, ClassVar

from pydantic import BaseModel

from engine.core.types import Document, ProviderAuth
from engine.tools.base import Action, BaseTool, require_auth
from engine.tools.drive import schemas as s
from engine.tools.drive.client import DriveClient


class DriveTool(BaseTool[s.DriveSettings]):
    """Google Drive for the org's shared drive."""

    name: ClassVar[str] = "drive"
    provider: ClassVar[str] = "google"
    owns: ClassVar[tuple[str, ...]] = ("googleapiclient",)
    syncs: ClassVar[bool] = True
    settings_model: ClassVar[type[BaseModel]] = s.DriveSettings
    actions: ClassVar[Mapping[str, Action]] = {
        "search_files": Action("Search files by name or content.", s.SearchFilesParams, s.FileList),
        "list_folder": Action("List the files in a folder.", s.ListFolderParams, s.FileList),
    }

    async def execute(self, action: str, params: BaseModel, auth: ProviderAuth | None) -> BaseModel:
        client = DriveClient(require_auth(auth, self.provider), self.settings)
        handlers: dict[str, Callable[[Any], Awaitable[BaseModel]]] = {
            "search_files": client.search_files,
            "list_folder": client.list_folder,
        }
        return await handlers[action](params)

    def documents(
        self, auth: ProviderAuth | None, since: datetime | None, source_id: str = ""
    ) -> AsyncIterator[Document]:
        """Documents changed since the time, or the one named by source_id."""
        raise NotImplementedError
