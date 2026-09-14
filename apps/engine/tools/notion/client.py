"""The Notion API."""

from __future__ import annotations

from engine.core.types import ProviderAuth
from engine.tools.notion.schemas import (
    CreatePageParams,
    GetPageParams,
    NotionSettings,
    Page,
    PageContent,
    PageList,
    QueryDatabaseParams,
    UpdatePageParams,
)


class NotionClient:
    """Calls Notion with the org's workspace credential."""

    def __init__(self, auth: ProviderAuth, settings: NotionSettings) -> None:
        self._auth = auth
        self._settings = settings

    async def query_database(self, params: QueryDatabaseParams) -> PageList:
        """Pages matching the filter, at most max_results."""
        raise NotImplementedError

    async def get_page(self, params: GetPageParams) -> PageContent:
        """The page and its blocks as text."""
        raise NotImplementedError

    async def create_page(self, params: CreatePageParams) -> Page:
        """The created page."""
        raise NotImplementedError

    async def update_page(self, params: UpdatePageParams) -> Page:
        """The page after the update."""
        raise NotImplementedError
