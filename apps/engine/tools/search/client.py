"""Web search and campus portal scraping over httpx and BeautifulSoup."""

from __future__ import annotations

from engine.tools.search.schemas import CampusOrgsParams, Hits, SearchSettings, WebSearchParams


class SearchClient:
    """Fetches and parses public pages."""

    def __init__(self, settings: SearchSettings) -> None:
        self._settings = settings

    async def web_search(self, params: WebSearchParams) -> Hits:
        """Results for the query."""
        raise NotImplementedError

    async def campus_orgs(self, params: CampusOrgsParams) -> Hits:
        """Organizations on campus_portal_url matching the keywords."""
        raise NotImplementedError
