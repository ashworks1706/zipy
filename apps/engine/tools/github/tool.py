"""The github tool."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, ClassVar

from pydantic import BaseModel

from engine.core.types import ProviderAuth, RequestContext
from engine.tools.base import Action, BaseTool, first_set, require_auth
from engine.tools.github import schemas as s
from engine.tools.github.client import GithubClient


class GithubTool(BaseTool[s.GithubSettings]):
    """GitHub issues, pull requests and repository files."""

    name: ClassVar[str] = "github"
    provider: ClassVar[str] = "github"
    owns: ClassVar[tuple[str, ...]] = ()
    settings_model: ClassVar[type[BaseModel]] = s.GithubSettings
    actions: ClassVar[Mapping[str, Action]] = {
        "list_issues": Action(
            "List the issues and pull requests of a repository.", s.ListIssuesParams, s.IssueList
        ),
        "get_issue": Action(
            "Read one issue or pull request and its comments.", s.GetIssueParams, s.IssueDetail
        ),
        "search_issues": Action(
            "Search issues and pull requests across the org.", s.SearchIssuesParams, s.IssueList
        ),
        "get_file": Action("Read one file from a repository.", s.GetFileParams, s.FileContent),
        "create_issue": Action("Open a new issue.", s.CreateIssueParams, s.Issue),
        "comment": Action("Comment on an issue or pull request.", s.CommentParams, s.Comment),
    }

    def target(self, action: str, params: BaseModel) -> str:  # noqa: ARG002
        """The repository an action acts on, with the issue or path when it names one."""
        repo = first_set(params, "repo")
        detail = first_set(params, "number", "path", "query")
        return f"{repo}#{detail}" if repo and detail else repo or detail

    async def execute(
        self,
        ctx: RequestContext,  # noqa: ARG002 - github is scoped by the org's token
        action: str,
        params: BaseModel,
        auth: ProviderAuth | None,
    ) -> BaseModel:
        client = GithubClient(require_auth(auth, self.provider), self.settings)
        handlers: dict[str, Callable[[Any], Awaitable[BaseModel]]] = {
            "list_issues": client.list_issues,
            "get_issue": client.get_issue,
            "search_issues": client.search_issues,
            "get_file": client.get_file,
            "create_issue": client.create_issue,
            "comment": client.comment,
        }
        return await handlers[action](params)
