"""Params, results and settings of the github tool."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GithubSettings(_Model):
    """[tools.github] settings an org may override."""

    # Owner every unqualified repository name is read under.
    default_owner: str = ""
    max_results: int = 25


class Issue(_Model):
    """One issue or pull request. GitHub numbers both in the same sequence."""

    number: int
    title: str
    state: str
    url: str
    author: str = ""
    labels: list[str] = []
    is_pull_request: bool = False
    updated_at: datetime | None = None


class IssueList(_Model):
    """Issues in the order GitHub returned them."""

    issues: list[Issue]


class Comment(_Model):
    """One comment on an issue or pull request."""

    author: str
    body: str
    url: str


class IssueDetail(_Model):
    """An issue and its conversation."""

    issue: Issue
    body: str = ""
    comments: list[Comment] = []


class FileContent(_Model):
    """One file from a repository, as text."""

    path: str
    url: str
    text: str


class ListIssuesParams(_Model):
    """Issues of a repository, newest first."""

    repo: str
    state: str = "open"
    labels: list[str] = []


class GetIssueParams(_Model):
    """One issue or pull request and its comments."""

    repo: str
    number: int


class SearchIssuesParams(_Model):
    """Issues and pull requests matching a query, across the org's repositories."""

    query: str
    repo: str = ""


class GetFileParams(_Model):
    """One file from a repository, on a branch or the default one."""

    repo: str
    path: str
    ref: str = ""


class CreateIssueParams(_Model):
    """A new issue."""

    repo: str
    title: str
    body: str = ""
    labels: list[str] = []


class CommentParams(_Model):
    """A comment added to an issue or pull request."""

    repo: str
    number: int
    body: str
