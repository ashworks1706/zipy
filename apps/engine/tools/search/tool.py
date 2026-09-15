"""The search tool."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, ClassVar

from pydantic import BaseModel

from engine.core.types import ProviderAuth
from engine.tools.base import Action, BaseTool, first_set
from engine.tools.search import schemas as s
from engine.tools.search.client import SearchClient


class SearchTool(BaseTool[s.SearchSettings]):
    """Public web and campus portal search."""

    name: ClassVar[str] = "search"
    owns: ClassVar[tuple[str, ...]] = ("bs4",)
    settings_model: ClassVar[type[BaseModel]] = s.SearchSettings
    actions: ClassVar[Mapping[str, Action]] = {
        "web_search": Action("Search the web.", s.WebSearchParams, s.Hits),
        "campus_orgs": Action(
            "Find student organizations on the campus portal.", s.CampusOrgsParams, s.Hits
        ),
    }

    def target(self, action: str, params: BaseModel) -> str:  # noqa: ARG002
        """What was searched for."""
        return first_set(params, "query", "keywords")

    async def execute(
        self,
        action: str,
        params: BaseModel,
        auth: ProviderAuth | None,  # noqa: ARG002 - search needs no credential
    ) -> BaseModel:
        client = SearchClient(self.settings)
        handlers: dict[str, Callable[[Any], Awaitable[BaseModel]]] = {
            "web_search": client.web_search,
            "campus_orgs": client.campus_orgs,
        }
        return await handlers[action](params)
