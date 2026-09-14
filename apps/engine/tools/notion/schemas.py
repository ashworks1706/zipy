"""Params, results and settings of the notion tool."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NotionSettings(_Model):
    """[tools.notion] settings an org may override."""

    sync_hours: int = 6

    max_results: int = 25


class Page(_Model):
    """One Notion page, its properties flattened to plain values."""

    id: str
    title: str
    url: str
    properties: dict[str, Any] = {}


class QueryDatabaseParams(_Model):
    """Pages of a database, by name or id, optionally filtered and sorted."""

    database: str
    filter: dict[str, Any] | None = None
    sorts: list[dict[str, Any]] = []


class GetPageParams(_Model):
    """One page and its text content."""

    page_id: str


class PageList(_Model):
    """Pages in the order Notion returned them."""

    pages: list[Page]


class PageContent(_Model):
    """A page and its body as plain text."""

    page: Page
    text: str


class CreatePageParams(_Model):
    """A new page in a database."""

    database: str
    title: str
    properties: dict[str, Any] = {}


class UpdatePageParams(_Model):
    """Property changes to one page."""

    page_id: str
    properties: dict[str, Any]
