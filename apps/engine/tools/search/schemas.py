"""Params, results and settings of the search tool."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchSettings(_Model):
    """[tools.search] settings an org may override."""

    campus_portal_url: str
    max_results: int = 5


class Hit(_Model):
    """One search result."""

    title: str
    url: str
    snippet: str


class WebSearchParams(_Model):
    """A web query, optionally limited to one site."""

    query: str
    site: str = ""


class CampusOrgsParams(_Model):
    """Organizations on the campus portal matching keywords."""

    keywords: str


class Hits(_Model):
    """Results, best first."""

    hits: list[Hit]
