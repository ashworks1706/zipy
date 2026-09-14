"""The Google Drive API."""

from __future__ import annotations

from engine.core.types import ProviderAuth
from engine.tools.drive.schemas import DriveSettings, FileList, ListFolderParams, SearchFilesParams


class DriveClient:
    """Calls Drive with the org's Google credential."""

    def __init__(self, auth: ProviderAuth, settings: DriveSettings) -> None:
        self._auth = auth
        self._settings = settings

    async def search_files(self, params: SearchFilesParams) -> FileList:
        """Files matching the query, at most max_results."""
        raise NotImplementedError

    async def list_folder(self, params: ListFolderParams) -> FileList:
        """The files in the folder."""
        raise NotImplementedError
