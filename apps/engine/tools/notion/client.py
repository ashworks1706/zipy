"""The Notion API."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any

from notion_client import AsyncClient
from notion_client.errors import HTTPResponseError, RequestTimeoutError

from engine.core.types import CredentialError, Document, ProviderAuth, ToolError, ZipyError
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

SOURCE = "notion"
PAGE_SIZE = 100
ID = re.compile(
    r"^[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}$"
)


def _failed(action: str, exc: HTTPResponseError) -> ZipyError:
    """The error the model reads. Carries Notion's status and message, never the token."""
    code = str(getattr(exc, "code", ""))
    if exc.status == 401 or code == "unauthorized":
        return CredentialError(f"the Notion credential is expired or revoked: {exc}")
    return ToolError(f"Notion refused {action} with status {exc.status}: {exc}")


def _rich(parts: list[dict[str, Any]]) -> str:
    """One rich text array as plain text."""
    return "".join(str(part.get("plain_text", "")) for part in parts)


def _plain(prop: dict[str, Any]) -> Any:
    """One page property as a plain value the model can read."""
    kind = str(prop.get("type", ""))
    value = prop.get(kind)
    if kind in {"title", "rich_text"}:
        return _rich(value or [])
    if kind in {"select", "status"}:
        return str(value.get("name", "")) if value else ""
    if kind == "multi_select":
        return [str(item.get("name", "")) for item in value or []]
    if kind == "date":
        return str(value.get("start", "")) if value else ""
    if kind in {"people", "relation"}:
        return [str(item.get("id", "")) for item in value or []]
    if kind == "files":
        return [str(item.get("name", "")) for item in value or []]
    if kind == "formula":
        return value.get(str(value.get("type", "")), "") if value else ""
    if kind == "unique_id":
        return str(value.get("number", "")) if value else ""
    return value


def _title_of(properties: dict[str, Any]) -> str:
    """The value of the page's title property."""
    for prop in properties.values():
        if prop.get("type") == "title":
            return _rich(prop.get("title") or [])
    return ""


def _page(raw: dict[str, Any]) -> Page:
    """One page as the model sees it, its properties flattened."""
    properties = raw.get("properties") or {}
    return Page(
        id=str(raw.get("id", "")),
        title=_title_of(properties),
        url=str(raw.get("url", "")),
        properties={name: _plain(prop) for name, prop in properties.items()},
    )


def _blocks_text(blocks: list[dict[str, Any]]) -> str:
    """The text of a page's blocks, one block per line."""
    lines = []
    for block in blocks:
        kind = str(block.get("type", ""))
        body = block.get(kind)
        if isinstance(body, dict) and isinstance(body.get("rich_text"), list):
            text = _rich(body["rich_text"])
            if text:
                lines.append(text)
    return "\n".join(lines)


def _edited_at(raw: dict[str, Any]) -> datetime:
    """When the page was last edited, as an aware UTC time."""
    stamp = str(raw.get("last_edited_time", ""))
    if not stamp:
        return datetime.now(UTC)
    return datetime.fromisoformat(stamp).astimezone(UTC)


def _value(name: str, kind: str, value: Any) -> dict[str, Any]:
    """One plain value as the property value Notion's schema expects."""
    if kind in {"title", "rich_text"}:
        return {kind: [{"type": "text", "text": {"content": str(value)}}]}
    if kind == "number":
        return {"number": None if value is None else float(value)}
    if kind == "checkbox":
        return {"checkbox": bool(value)}
    if kind in {"select", "status"}:
        return {kind: {"name": str(value)}}
    if kind == "multi_select":
        items = value if isinstance(value, list) else [value]
        return {"multi_select": [{"name": str(item)} for item in items]}
    if kind == "date":
        return {"date": value if isinstance(value, dict) else {"start": str(value)}}
    if kind in {"url", "email", "phone_number"}:
        return {kind: str(value)}
    if kind in {"people", "relation"}:
        items = value if isinstance(value, list) else [value]
        return {kind: [{"id": str(item)} for item in items]}
    raise ToolError(f"the Notion property {name} is a {kind}, which Zipy cannot write")


class NotionClient:
    """Calls Notion with the org's workspace credential."""

    def __init__(self, auth: ProviderAuth, settings: NotionSettings) -> None:
        self._auth = auth
        self._settings = settings
        self._client: AsyncClient | None = None

    @property
    def api(self) -> AsyncClient:
        """The Notion SDK client holding the org's token."""
        if self._client is None:
            self._client = AsyncClient(auth=self._auth.access_token.get_secret_value())
        return self._client

    async def query_database(self, params: QueryDatabaseParams) -> PageList:
        """Pages matching the filter, at most max_results."""
        data_source = await self._data_source(params.database)
        body: dict[str, Any] = {"page_size": self._settings.max_results}
        if params.filter is not None:
            body["filter"] = params.filter
        if params.sorts:
            body["sorts"] = params.sorts
        raw = await self._call(
            "query_database", self.api.data_sources.query, data_source_id=data_source, **body
        )
        results = raw.get("results", [])[: self._settings.max_results]
        return PageList(pages=[_page(item) for item in results])

    async def get_page(self, params: GetPageParams) -> PageContent:
        """The page and its blocks as text."""
        raw = await self._call("get_page", self.api.pages.retrieve, page_id=params.page_id)
        return PageContent(page=_page(raw), text=await self._text(params.page_id))

    async def create_page(self, params: CreatePageParams) -> Page:
        """The created page."""
        data_source = await self._data_source(params.database)
        schema = await self._schema(data_source)
        properties = self._properties(schema, params.properties)
        properties[self._title_key(schema)] = _value("title", "title", params.title)
        raw = await self._call(
            "create_page",
            self.api.pages.create,
            parent={"type": "data_source_id", "data_source_id": data_source},
            properties=properties,
        )
        return _page(raw)

    async def update_page(self, params: UpdatePageParams) -> Page:
        """The page after the update."""
        if not params.properties:
            raise ToolError("update_page needs at least one property to change")
        current = await self._call("update_page", self.api.pages.retrieve, page_id=params.page_id)
        parent = current.get("parent") or {}
        data_source = str(parent.get("data_source_id") or parent.get("database_id") or "")
        if not data_source:
            raise ToolError(f"the Notion page {params.page_id} is not in a database")
        schema = await self._schema(data_source)
        raw = await self._call(
            "update_page",
            self.api.pages.update,
            page_id=params.page_id,
            properties=self._properties(schema, params.properties),
        )
        return _page(raw)

    async def documents(
        self, since: datetime | None, source_id: str = ""
    ) -> AsyncIterator[Document]:
        """Pages edited since the time, or the one named by source_id."""
        if source_id:
            raw = await self._call("documents", self.api.pages.retrieve, page_id=source_id)
            yield await self._document(raw)
            return
        cursor = ""
        while True:
            body: dict[str, Any] = {
                "filter": {"property": "object", "value": "page"},
                "sort": {"direction": "descending", "timestamp": "last_edited_time"},
                "page_size": PAGE_SIZE,
            }
            if cursor:
                body["start_cursor"] = cursor
            raw = await self._call("documents", self.api.search, **body)
            for item in raw.get("results", []):
                if since is not None and _edited_at(item) <= since.astimezone(UTC):
                    return
                yield await self._document(item)
            cursor = str(raw.get("next_cursor") or "")
            if not raw.get("has_more") or not cursor:
                return

    async def _document(self, raw: dict[str, Any]) -> Document:
        """One page as a searchable document."""
        page = _page(raw)
        return Document(
            source=SOURCE,
            source_id=page.id,
            title=page.title,
            text=await self._text(page.id),
            updated_at=_edited_at(raw),
            metadata={"url": page.url},
        )

    async def _text(self, page_id: str) -> str:
        """Every block of the page as plain text."""
        blocks: list[dict[str, Any]] = []
        cursor = ""
        while True:
            body: dict[str, Any] = {"block_id": page_id, "page_size": PAGE_SIZE}
            if cursor:
                body["start_cursor"] = cursor
            raw = await self._call("get_page", self.api.blocks.children.list, **body)
            blocks.extend(raw.get("results", []))
            cursor = str(raw.get("next_cursor") or "")
            if not raw.get("has_more") or not cursor:
                break
        return _blocks_text(blocks)

    async def _data_source(self, database: str) -> str:
        """The data source a database name or id refers to."""
        name = database.strip()
        if not name:
            raise ToolError("a database name or id is needed")
        if ID.match(name):
            return await self._data_source_of(name)
        raw = await self._call(
            "query_database",
            self.api.search,
            query=name,
            filter={"property": "object", "value": "data_source"},
            page_size=self._settings.max_results,
        )
        results = raw.get("results", [])
        if not results:
            raise ToolError(f"no Notion database named {name} is shared with Zipy")
        wanted = name.casefold()
        for item in results:
            if _source_name(item).casefold() == wanted:
                return str(item.get("id", ""))
        return str(results[0].get("id", ""))

    async def _data_source_of(self, identifier: str) -> str:
        """The first data source of a database id, or the id itself when it is one already."""
        try:
            raw = await self._call(
                "query_database", self.api.databases.retrieve, database_id=identifier
            )
        except ToolError:
            return identifier
        sources = raw.get("data_sources") or []
        if not sources:
            raise ToolError(f"the Notion database {identifier} holds no data source")
        return str(sources[0].get("id", ""))

    async def _schema(self, data_source: str) -> dict[str, Any]:
        """The data source's property schema, by property name."""
        raw = await self._call(
            "create_page", self.api.data_sources.retrieve, data_source_id=data_source
        )
        properties = raw.get("properties") or {}
        return dict(properties)

    def _properties(self, schema: dict[str, Any], given: dict[str, Any]) -> dict[str, Any]:
        """The given plain values as Notion property values, checked against the schema."""
        built: dict[str, Any] = {}
        for name, value in given.items():
            if name not in schema:
                known = ", ".join(sorted(schema)) or "none"
                raise ToolError(f"the Notion database has no property {name}; it has {known}")
            built[name] = _value(name, str(schema[name].get("type", "")), value)
        return built

    def _title_key(self, schema: dict[str, Any]) -> str:
        """The name of the schema's title property."""
        for name, prop in schema.items():
            if prop.get("type") == "title":
                return str(name)
        raise ToolError("the Notion database has no title property")

    async def _call(self, action: str, endpoint: Callable[..., Any], **body: Any) -> Any:
        """One Notion request, with its failures turned into errors the model reads."""
        try:
            return await endpoint(**body)
        except HTTPResponseError as exc:
            raise _failed(action, exc) from exc
        except RequestTimeoutError as exc:
            raise ToolError(f"Notion did not answer {action} in time") from exc


def _source_name(raw: dict[str, Any]) -> str:
    """The name of a data source search result."""
    name = raw.get("name")
    if isinstance(name, list):
        return _rich(name)
    if isinstance(name, str):
        return name
    title = raw.get("title")
    return _rich(title) if isinstance(title, list) else ""
