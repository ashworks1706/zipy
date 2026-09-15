"""Web search and campus portal scraping over httpx and BeautifulSoup."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Tag

from engine.core.types import ToolError
from engine.tools.search.schemas import CampusOrgsParams, Hit, Hits, SearchSettings, WebSearchParams

WEB_SEARCH_URL = "https://html.duckduckgo.com/html/"
USER_AGENT = "Mozilla/5.0 (compatible; Zipy)"
TIMEOUT_SECS = 20.0
SNIPPET_CHARS = 300
SPACE = re.compile(r"\s+")


def _clean(value: str) -> str:
    """One line of text with its whitespace collapsed."""
    return SPACE.sub(" ", value).strip()


def _text(node: Tag | None) -> str:
    """The text of a node, or the empty string when it is missing."""
    return _clean(node.get_text(" ")) if node is not None else ""


def _href(node: Tag) -> str:
    """The href of an anchor, as a string."""
    value = node.get("href")
    return value if isinstance(value, str) else ""


def _direct(href: str) -> str:
    """The destination of a search result link, unwrapping the engine's redirect."""
    if not href:
        return ""
    target = href if href.startswith("http") else f"https:{href}" if href.startswith("//") else href
    wrapped = parse_qs(urlparse(target).query).get("uddg")
    return wrapped[0] if wrapped else target


class SearchClient:
    """Fetches and parses public pages."""

    def __init__(
        self, settings: SearchSettings, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._settings = settings
        self._transport = transport

    async def web_search(self, params: WebSearchParams) -> Hits:
        """Results for the query."""
        query = _clean(params.query)
        if not query:
            raise ToolError("web_search needs a query")
        if params.site:
            query = f"site:{_clean(params.site)} {query}"
        page = await self._fetch("web_search", WEB_SEARCH_URL, {"q": query}, post=True)
        return Hits(hits=self._results(page))

    async def campus_orgs(self, params: CampusOrgsParams) -> Hits:
        """Organizations on campus_portal_url matching the keywords."""
        keywords = _clean(params.keywords)
        if not keywords:
            raise ToolError("campus_orgs needs keywords")
        url = self._settings.campus_portal_url
        page = await self._fetch("campus_orgs", url, {"query": keywords})
        return Hits(hits=self._organizations(page, url))

    def _results(self, page: str) -> list[Hit]:
        """The result blocks of a search engine page, best first."""
        soup = BeautifulSoup(page, "html.parser")
        hits: list[Hit] = []
        for block in soup.select("div.result, div.web-result"):
            link = block.select_one("a.result__a")
            if link is None:
                continue
            url = _direct(_href(link))
            title = _text(link)
            if not url or not title:
                continue
            hits.append(
                Hit(title=title, url=url, snippet=_text(block.select_one(".result__snippet")))
            )
            if len(hits) >= self._settings.max_results:
                break
        return hits

    def _organizations(self, page: str, base: str) -> list[Hit]:
        """The organization links of the campus portal page."""
        soup = BeautifulSoup(page, "html.parser")
        hits: list[Hit] = []
        seen: set[str] = set()
        for link in soup.find_all("a"):
            if not isinstance(link, Tag):
                continue
            href = _href(link)
            if "/organization" not in href:
                continue
            url = urljoin(base, href)
            title = _text(link)
            if not title or url in seen:
                continue
            seen.add(url)
            parent = link.parent
            snippet = _text(parent if isinstance(parent, Tag) else None)[:SNIPPET_CHARS]
            hits.append(Hit(title=title, url=url, snippet=snippet))
            if len(hits) >= self._settings.max_results:
                break
        return hits

    async def _fetch(self, action: str, url: str, query: dict[str, str], post: bool = False) -> str:
        """One public page, as text."""
        headers = {"User-Agent": USER_AGENT, "Accept": "text/html"}
        request: dict[str, Any] = {"data": query} if post else {"params": query}
        try:
            async with httpx.AsyncClient(
                timeout=TIMEOUT_SECS, transport=self._transport, follow_redirects=True
            ) as client:
                response = await client.request(
                    "POST" if post else "GET", url, headers=headers, **request
                )
        except httpx.HTTPError as exc:
            raise ToolError(f"{action} could not reach the page: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            raise ToolError(f"{action} was refused with status {response.status_code}")
        return response.text
