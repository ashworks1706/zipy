"""The search tool: its schemas, the pages it fetches, and what it parses out of them."""

from datetime import UTC, datetime

import httpx
import pytest

from engine.core.types import (
    ChannelRef,
    MemberRef,
    OrgId,
    RequestContext,
    Role,
    ToolError,
    WorkspaceRef,
)
from engine.tools.search import tool as tool_module
from engine.tools.search.client import SearchClient
from engine.tools.search.schemas import CampusOrgsParams, SearchSettings, WebSearchParams
from engine.tools.search.tool import SearchTool


def context():
    return RequestContext(
        org_id=OrgId("org-1"),
        channel=ChannelRef(WorkspaceRef("discord", "g1"), "c1"),
        member=MemberRef("discord", "u1"),
        role=Role.OFFICER,
        display_name="Ash",
        request_id="req-1",
        received_at=datetime(2026, 9, 19, tzinfo=UTC),
    )


PORTAL = "https://asu.campuslabs.com/engage/organizations"

RESULTS = """
<html><body>
<div class="result results_links web-result">
  <h2 class="result__title">
    <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.asu.edu%2Fmu&amp;rut=x">
      MU room booking
    </a>
  </h2>
  <a class="result__snippet">Reserve a room in the Memorial Union.</a>
</div>
<div class="result results_links web-result">
  <h2 class="result__title">
    <a class="result__a" href="https://eoss.asu.edu/mu">Memorial Union</a>
  </h2>
  <a class="result__snippet">Hours and policies.</a>
</div>
<div class="result results_links"><span>an advert with no link</span></div>
</body></html>
"""

PORTAL_PAGE = """
<html><body>
<div class="card">
  <a href="/engage/organization/ai-club">AI Club</a><p>Building AI projects.</p>
</div>
<div class="card">
  <a href="/engage/organization/robotics">Robotics Club</a><p>Sun Devil Robotics.</p>
</div>
<div class="card"><a href="/engage/organization/ai-club">AI Club</a></div>
<a href="/engage/events/kickoff">Kickoff</a>
</body></html>
"""


class Web:
    """A stand-in for the public web. Routes are matched by the part of the url they name."""

    def __init__(self, routes, failure=None):
        self.requests = []
        self._routes = routes
        self._failure = failure

    def handle(self, request):
        self.requests.append(request)
        if self._failure is not None:
            raise self._failure
        for key, (status, body) in self._routes.items():
            if key in str(request.url):
                return httpx.Response(status, text=body)
        return httpx.Response(404, text="")


def web(monkeypatch, routes=None, failure=None):
    """Put a stand-in web behind the tool and return it."""
    pages = Web(routes or {}, failure)
    transport = httpx.MockTransport(pages.handle)
    monkeypatch.setattr(
        tool_module, "SearchClient", lambda settings: SearchClient(settings, transport=transport)
    )
    return pages


def tool(**settings):
    return SearchTool(SearchSettings(campus_portal_url=PORTAL, **settings))


def test_a_campus_org_query_parses():
    assert CampusOrgsParams(keywords="AI robotics").keywords == "AI robotics"


async def test_web_search_posts_the_query_and_unwraps_the_result_links(monkeypatch):
    pages = web(monkeypatch, {"duckduckgo.com/html": (200, RESULTS)})

    result = await tool().execute(
        context(), "web_search", WebSearchParams(query="MU room booking"), None
    )

    sent = pages.requests[0]
    assert sent.method == "POST"
    assert b"q=MU+room+booking" in sent.content
    assert [hit.url for hit in result.hits] == ["https://www.asu.edu/mu", "https://eoss.asu.edu/mu"]
    assert result.hits[0].title == "MU room booking"
    assert result.hits[0].snippet == "Reserve a room in the Memorial Union."


async def test_web_search_limits_the_query_to_one_site(monkeypatch):
    pages = web(monkeypatch, {"duckduckgo.com/html": (200, RESULTS)})

    await tool().execute(
        context(), "web_search", WebSearchParams(query="room policy", site="asu.edu"), None
    )

    assert b"site%3Aasu.edu+room+policy" in pages.requests[0].content


async def test_web_search_stops_at_the_orgs_max_results(monkeypatch):
    web(monkeypatch, {"duckduckgo.com/html": (200, RESULTS)})

    result = await tool(max_results=1).execute(
        context(), "web_search", WebSearchParams(query="mu"), None
    )

    assert len(result.hits) == 1


async def test_web_search_needs_a_query(monkeypatch):
    web(monkeypatch)

    with pytest.raises(ToolError, match="needs a query"):
        await tool().execute(context(), "web_search", WebSearchParams(query="   "), None)


async def test_campus_orgs_asks_the_portal_and_keeps_organization_links_only(monkeypatch):
    pages = web(monkeypatch, {"campuslabs.com": (200, PORTAL_PAGE)})

    result = await tool().execute(
        context(), "campus_orgs", CampusOrgsParams(keywords="AI robotics"), None
    )

    sent = pages.requests[0]
    assert sent.method == "GET"
    assert sent.url.params["query"] == "AI robotics"
    assert [hit.title for hit in result.hits] == ["AI Club", "Robotics Club"]
    assert result.hits[0].url == "https://asu.campuslabs.com/engage/organization/ai-club"
    assert "Building AI projects." in result.hits[0].snippet


async def test_campus_orgs_needs_keywords(monkeypatch):
    web(monkeypatch)

    with pytest.raises(ToolError, match="needs keywords"):
        await tool().execute(context(), "campus_orgs", CampusOrgsParams(keywords=" "), None)


async def test_a_page_that_refuses_becomes_a_tool_error_naming_the_status(monkeypatch):
    web(monkeypatch, {"campuslabs.com": (503, "")})

    with pytest.raises(ToolError) as caught:
        await tool().execute(context(), "campus_orgs", CampusOrgsParams(keywords="AI"), None)

    assert "503" in str(caught.value)


async def test_a_page_that_cannot_be_reached_becomes_a_tool_error(monkeypatch):
    web(monkeypatch, failure=httpx.ConnectError("no route to host"))

    with pytest.raises(ToolError, match="could not reach the page"):
        await tool().execute(context(), "web_search", WebSearchParams(query="mu"), None)


async def test_a_page_with_nothing_to_parse_is_no_results_rather_than_an_error(monkeypatch):
    web(monkeypatch, {"duckduckgo.com/html": (200, "<html><body>nothing</body></html>")})

    result = await tool().execute(context(), "web_search", WebSearchParams(query="mu"), None)

    assert result.hits == []
