"""The notion tool: its schemas, the calls it makes, and what it makes of the answers."""

from datetime import UTC, datetime

import httpx
import pytest
from notion_client.errors import APIResponseError
from pydantic import SecretStr

from engine.core.types import CredentialError, OrgId, ProviderAuth, ToolError
from engine.tools.notion import client as client_module
from engine.tools.notion.schemas import (
    CreatePageParams,
    GetPageParams,
    NotionSettings,
    QueryDatabaseParams,
    UpdatePageParams,
)
from engine.tools.notion.tool import NotionTool

TOKEN = "secret_a-notion-workspace-token"
DATA_SOURCE = "11111111-2222-3333-4444-555555555555"
DATABASE_ID = "99999999-8888-7777-6666-555555555555"


class FakeEndpoint:
    """One Notion endpoint that records what it was called with."""

    def __init__(self, notion, name):
        self._notion = notion
        self._name = name

    async def __call__(self, **body):
        self._notion.calls.append((self._name, body))
        if self._notion.error is not None:
            raise self._notion.error
        return self._notion.answer(self._name)


class Group:
    """A group of endpoints, such as pages or data_sources."""

    def __init__(self, **endpoints):
        for name, endpoint in endpoints.items():
            setattr(self, name, endpoint)


class FakeNotion:
    """A stand-in for notion_client.AsyncClient. Answers are consumed in order."""

    def __init__(self, results=None, error=None):
        self.calls = []
        self.error = error
        self._results = {k: list(v) for k, v in (results or {}).items()}
        self.search = FakeEndpoint(self, "search")
        self.pages = Group(
            retrieve=FakeEndpoint(self, "pages.retrieve"),
            create=FakeEndpoint(self, "pages.create"),
            update=FakeEndpoint(self, "pages.update"),
        )
        self.databases = Group(retrieve=FakeEndpoint(self, "databases.retrieve"))
        self.data_sources = Group(
            query=FakeEndpoint(self, "data_sources.query"),
            retrieve=FakeEndpoint(self, "data_sources.retrieve"),
        )
        self.blocks = Group(children=Group(list=FakeEndpoint(self, "blocks.children.list")))

    def answer(self, name):
        queued = self._results.get(name)
        if not queued:
            return {}
        return queued.pop(0) if len(queued) > 1 else queued[0]


def notion(monkeypatch, results=None, error=None):
    """Put a fake Notion client behind the tool and return it."""
    fake = FakeNotion(results, error)
    monkeypatch.setattr(client_module, "AsyncClient", lambda **kwargs: fake)
    return fake


def auth(provider="notion"):
    return ProviderAuth(
        org_id=OrgId("org-1"),
        provider=provider,
        access_token=SecretStr(TOKEN),
        scopes=(),
        expires_at=None,
    )


def tool(**settings):
    return NotionTool(NotionSettings(**settings))


def api_error(status, code, message):
    return APIResponseError(
        code=code,
        status=status,
        message=message,
        headers=httpx.Headers(),
        raw_body_text="{}",
    )


SCHEMA = {
    "properties": {
        "Name": {"type": "title"},
        "Assignee": {"type": "rich_text"},
        "Due": {"type": "date"},
        "Done": {"type": "checkbox"},
        "Tags": {"type": "multi_select"},
        "Files": {"type": "files"},
    }
}

PAGE = {
    "id": "page-1",
    "url": "https://notion.so/page-1",
    "last_edited_time": "2026-09-14T17:30:00.000Z",
    "parent": {"type": "data_source_id", "data_source_id": DATA_SOURCE},
    "properties": {
        "Name": {"type": "title", "title": [{"plain_text": "Design the flyer"}]},
        "Assignee": {"type": "rich_text", "rich_text": [{"plain_text": "Maria"}]},
        "Due": {"type": "date", "date": {"start": "2026-09-25"}},
        "Done": {"type": "checkbox", "checkbox": False},
        "Tags": {"type": "multi_select", "multi_select": [{"name": "design"}]},
    },
}

BLOCKS = {
    "results": [
        {"type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "Notes"}]}},
        {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Ignore this line."}]}},
        {"type": "image", "image": {"file": {"url": "https://example.test/x.png"}}},
    ],
    "has_more": False,
}


def test_a_task_with_an_assignee_and_due_date_parses():
    params = CreatePageParams(
        database="Tasks",
        title="Design the flyer for the AI workshop",
        properties={"Assignee": "Maria", "Due": "2026-09-25"},
    )
    assert params.properties["Assignee"] == "Maria"


async def test_query_database_finds_the_database_by_name_and_queries_its_data_source(monkeypatch):
    fake = notion(
        monkeypatch,
        {
            "search": [{"results": [{"id": DATA_SOURCE, "name": "Tasks"}]}],
            "data_sources.query": [{"results": [PAGE]}],
        },
    )

    result = await tool().execute("query_database", QueryDatabaseParams(database="Tasks"), auth())

    search, query = fake.calls
    assert search[1]["query"] == "Tasks"
    assert search[1]["filter"] == {"property": "object", "value": "data_source"}
    assert query[1]["data_source_id"] == DATA_SOURCE
    assert query[1]["page_size"] == 25
    page = result.pages[0]
    assert page.title == "Design the flyer"
    assert page.properties["Assignee"] == "Maria"
    assert page.properties["Due"] == "2026-09-25"
    assert page.properties["Tags"] == ["design"]
    assert page.properties["Done"] is False


async def test_query_database_prefers_the_data_source_whose_name_matches(monkeypatch):
    fake = notion(
        monkeypatch,
        {
            "search": [
                {
                    "results": [
                        {"id": "other", "name": "Task archive"},
                        {"id": DATA_SOURCE, "name": "Tasks"},
                    ]
                }
            ],
            "data_sources.query": [{"results": []}],
        },
    )

    await tool().execute("query_database", QueryDatabaseParams(database="tasks"), auth())

    assert fake.calls[1][1]["data_source_id"] == DATA_SOURCE


async def test_query_database_resolves_a_database_id_through_its_data_sources(monkeypatch):
    fake = notion(
        monkeypatch,
        {
            "databases.retrieve": [{"data_sources": [{"id": DATA_SOURCE}]}],
            "data_sources.query": [{"results": []}],
        },
    )

    await tool().execute("query_database", QueryDatabaseParams(database=DATABASE_ID), auth())

    assert fake.calls[0] == ("databases.retrieve", {"database_id": DATABASE_ID})
    assert fake.calls[1][1]["data_source_id"] == DATA_SOURCE


async def test_query_database_passes_a_filter_and_sorts_through(monkeypatch):
    fake = notion(
        monkeypatch,
        {
            "search": [{"results": [{"id": DATA_SOURCE, "name": "Tasks"}]}],
            "data_sources.query": [{"results": []}],
        },
    )
    params = QueryDatabaseParams(
        database="Tasks",
        filter={"property": "Done", "checkbox": {"equals": False}},
        sorts=[{"property": "Due", "direction": "ascending"}],
    )

    await tool().execute("query_database", params, auth())

    sent = fake.calls[1][1]
    assert sent["filter"] == {"property": "Done", "checkbox": {"equals": False}}
    assert sent["sorts"] == [{"property": "Due", "direction": "ascending"}]


async def test_a_database_no_one_shared_says_so(monkeypatch):
    notion(monkeypatch, {"search": [{"results": []}]})

    with pytest.raises(ToolError, match="no Notion database named Budget"):
        await tool().execute("query_database", QueryDatabaseParams(database="Budget"), auth())


async def test_get_page_returns_the_page_and_its_block_text(monkeypatch):
    notion(monkeypatch, {"pages.retrieve": [PAGE], "blocks.children.list": [BLOCKS]})

    result = await tool().execute("get_page", GetPageParams(page_id="page-1"), auth())

    assert result.page.id == "page-1"
    assert result.text == "Notes\nIgnore this line."


async def test_create_page_builds_notion_property_values_from_plain_ones(monkeypatch):
    fake = notion(
        monkeypatch,
        {
            "search": [{"results": [{"id": DATA_SOURCE, "name": "Tasks"}]}],
            "data_sources.retrieve": [SCHEMA],
            "pages.create": [PAGE],
        },
    )
    params = CreatePageParams(
        database="Tasks",
        title="Design the flyer",
        properties={"Assignee": "Maria", "Due": "2026-09-25", "Done": False, "Tags": ["design"]},
    )

    result = await tool().execute("create_page", params, auth())

    sent = fake.calls[-1][1]
    assert sent["parent"] == {"type": "data_source_id", "data_source_id": DATA_SOURCE}
    assert sent["properties"]["Name"]["title"][0]["text"]["content"] == "Design the flyer"
    assert sent["properties"]["Assignee"]["rich_text"][0]["text"]["content"] == "Maria"
    assert sent["properties"]["Due"] == {"date": {"start": "2026-09-25"}}
    assert sent["properties"]["Done"] == {"checkbox": False}
    assert sent["properties"]["Tags"] == {"multi_select": [{"name": "design"}]}
    assert result.id == "page-1"


async def test_a_property_the_database_does_not_have_names_the_ones_it_does(monkeypatch):
    notion(
        monkeypatch,
        {
            "search": [{"results": [{"id": DATA_SOURCE, "name": "Tasks"}]}],
            "data_sources.retrieve": [SCHEMA],
        },
    )
    params = CreatePageParams(database="Tasks", title="x", properties={"Owner": "Maria"})

    with pytest.raises(ToolError) as caught:
        await tool().execute("create_page", params, auth())

    assert "no property Owner" in str(caught.value)
    assert "Assignee" in str(caught.value)


async def test_a_property_type_zipy_cannot_write_says_so(monkeypatch):
    notion(
        monkeypatch,
        {
            "search": [{"results": [{"id": DATA_SOURCE, "name": "Tasks"}]}],
            "data_sources.retrieve": [SCHEMA],
        },
    )
    params = CreatePageParams(database="Tasks", title="x", properties={"Files": ["a.png"]})

    with pytest.raises(ToolError, match="Files is a files"):
        await tool().execute("create_page", params, auth())


async def test_update_page_reads_the_pages_schema_before_writing(monkeypatch):
    fake = notion(
        monkeypatch,
        {"pages.retrieve": [PAGE], "data_sources.retrieve": [SCHEMA], "pages.update": [PAGE]},
    )
    params = UpdatePageParams(page_id="page-1", properties={"Done": True})

    await tool().execute("update_page", params, auth())

    assert [call[0] for call in fake.calls] == [
        "pages.retrieve",
        "data_sources.retrieve",
        "pages.update",
    ]
    assert fake.calls[-1][1]["properties"] == {"Done": {"checkbox": True}}


async def test_update_page_without_a_change_says_so(monkeypatch):
    notion(monkeypatch)

    with pytest.raises(ToolError, match="at least one property"):
        await tool().execute(
            "update_page", UpdatePageParams(page_id="page-1", properties={}), auth()
        )


async def test_documents_yields_one_page_with_its_text(monkeypatch):
    notion(monkeypatch, {"pages.retrieve": [PAGE], "blocks.children.list": [BLOCKS]})

    found = [doc async for doc in tool().documents(auth(), None, "page-1")]

    assert found[0].source == "notion"
    assert found[0].source_id == "page-1"
    assert found[0].title == "Design the flyer"
    assert found[0].text.startswith("Notes")
    assert found[0].metadata["url"] == "https://notion.so/page-1"


async def test_documents_stops_at_pages_edited_before_the_sync_point(monkeypatch):
    old = dict(PAGE, id="page-old", last_edited_time="2026-08-01T00:00:00.000Z")
    notion(
        monkeypatch,
        {
            "search": [{"results": [PAGE, old], "has_more": False}],
            "blocks.children.list": [BLOCKS],
        },
    )

    found = [doc async for doc in tool().documents(auth(), datetime(2026, 9, 1, tzinfo=UTC))]

    assert [doc.source_id for doc in found] == ["page-1"]


async def test_a_notion_refusal_becomes_a_tool_error_naming_the_message(monkeypatch):
    notion(monkeypatch, error=api_error(400, "validation_error", "body failed validation"))

    with pytest.raises(ToolError) as caught:
        await tool().execute("get_page", GetPageParams(page_id="page-1"), auth())

    assert "400" in str(caught.value)
    assert "body failed validation" in str(caught.value)


async def test_a_revoked_token_becomes_a_credential_error(monkeypatch):
    notion(monkeypatch, error=api_error(401, "unauthorized", "API token is invalid"))

    with pytest.raises(CredentialError, match="expired or revoked"):
        await tool().execute("get_page", GetPageParams(page_id="page-1"), auth())


async def test_a_tool_without_the_orgs_notion_account_refuses_to_run():
    params = GetPageParams(page_id="page-1")

    with pytest.raises(CredentialError, match="notion is not connected"):
        await tool().execute("get_page", params, None)

    with pytest.raises(CredentialError, match="notion is not connected"):
        await tool().execute("get_page", params, auth(provider="google"))


async def test_the_token_reaches_neither_a_result_nor_an_error(monkeypatch):
    notion(monkeypatch, {"pages.retrieve": [PAGE], "blocks.children.list": [BLOCKS]})
    result = await tool().execute("get_page", GetPageParams(page_id="page-1"), auth())
    assert TOKEN not in result.model_dump_json()

    notion(monkeypatch, error=api_error(401, "unauthorized", "API token is invalid"))
    with pytest.raises(CredentialError) as caught:
        await tool().execute("get_page", GetPageParams(page_id="page-1"), auth())
    assert TOKEN not in str(caught.value)
