"""The notion tool."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from datetime import datetime
from typing import Any, ClassVar

from pydantic import BaseModel

from engine.core.types import Document, ProviderAuth
from engine.tools.base import Action, BaseTool, first_set, require_auth
from engine.tools.notion import schemas as s
from engine.tools.notion.client import NotionClient


class NotionTool(BaseTool[s.NotionSettings]):
    """Notion for the org's workspace."""

    name: ClassVar[str] = "notion"
    provider: ClassVar[str] = "notion"
    owns: ClassVar[tuple[str, ...]] = ("notion_client",)
    syncs: ClassVar[bool] = True
    settings_model: ClassVar[type[BaseModel]] = s.NotionSettings
    actions: ClassVar[Mapping[str, Action]] = {
        "query_database": Action("Query a database for pages.", s.QueryDatabaseParams, s.PageList),
        "get_page": Action("Read one page.", s.GetPageParams, s.PageContent),
        "create_page": Action("Create a page in a database.", s.CreatePageParams, s.Page),
        "update_page": Action("Change a page's properties.", s.UpdatePageParams, s.Page),
    }

    def target(self, action: str, params: BaseModel) -> str:  # noqa: ARG002
        """The page or database an action acts on."""
        return first_set(params, "page_id", "database")

    async def execute(self, action: str, params: BaseModel, auth: ProviderAuth | None) -> BaseModel:
        client = NotionClient(require_auth(auth, self.provider), self.settings)
        handlers: dict[str, Callable[[Any], Awaitable[BaseModel]]] = {
            "query_database": client.query_database,
            "get_page": client.get_page,
            "create_page": client.create_page,
            "update_page": client.update_page,
        }
        return await handlers[action](params)

    def documents(
        self, auth: ProviderAuth | None, since: datetime | None, source_id: str = ""
    ) -> AsyncIterator[Document]:
        """Documents changed since the time, or the one named by source_id."""
        client = NotionClient(require_auth(auth, self.provider), self.settings)
        return client.documents(since, source_id)
