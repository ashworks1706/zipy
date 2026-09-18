"""The GitHub REST API over httpx."""

from __future__ import annotations

import base64
import binascii
from typing import Any

import httpx

from engine.core.types import CredentialError, ProviderAuth, ToolError, ZipyError
from engine.tools.github.schemas import (
    Comment,
    CommentParams,
    CreateIssueParams,
    FileContent,
    GetFileParams,
    GetIssueParams,
    GithubSettings,
    Issue,
    IssueDetail,
    IssueList,
    ListIssuesParams,
    SearchIssuesParams,
)

API = "https://api.github.com"
ACCEPT = "application/vnd.github+json"
VERSION = "2022-11-28"
TIMEOUT_SECS = 30.0

# Comments read back for one issue.
COMMENT_LIMIT = 50

# Bytes of a file the tool will carry. A larger file is refused rather than truncated silently.
MAX_FILE_BYTES = 200_000


def _failed(action: str, status: int) -> ZipyError:
    """The error the model reads. Carries the status, never the token."""
    if status in (401, 403):
        return CredentialError("the GitHub credential is expired, revoked or lacks the scope")
    if status == 404:
        return ToolError(f"{action} found nothing under that owner, repository or number")
    return ToolError(f"GitHub refused {action} with status {status}")


def _issue(raw: dict[str, Any]) -> Issue:
    """One issue or pull request payload as an Issue."""
    user = raw.get("user") or {}
    return Issue(
        number=int(raw.get("number", 0)),
        title=str(raw.get("title", "")),
        state=str(raw.get("state", "")),
        url=str(raw.get("html_url", "")),
        author=str(user.get("login", "")),
        labels=[str(label.get("name", "")) for label in raw.get("labels") or []],
        is_pull_request="pull_request" in raw,
        updated_at=raw.get("updated_at"),
    )


class GithubClient:
    """Reads and writes the org's repositories with one connected credential."""

    def __init__(
        self,
        auth: ProviderAuth,
        settings: GithubSettings,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._auth = auth
        self._settings = settings
        self._transport = transport

    def _repo(self, repo: str) -> str:
        """owner/name for a repository, filling in default_owner when only a name was given."""
        name = repo.strip().strip("/")
        if "/" in name:
            return name
        if not self._settings.default_owner:
            raise ToolError(
                f"repo {name} has no owner and tools.github.default_owner is not set; "
                "give it as owner/name"
            )
        return f"{self._settings.default_owner}/{name}"

    async def list_issues(self, params: ListIssuesParams) -> IssueList:
        """Issues of a repository, newest first. GitHub includes pull requests here."""
        query: dict[str, Any] = {
            "state": params.state,
            "per_page": self._settings.max_results,
            "sort": "updated",
        }
        if params.labels:
            query["labels"] = ",".join(params.labels)
        raw = await self._get("list_issues", f"/repos/{self._repo(params.repo)}/issues", query)
        return IssueList(issues=[_issue(entry) for entry in raw if isinstance(entry, dict)])

    async def get_issue(self, params: GetIssueParams) -> IssueDetail:
        """One issue or pull request and its comments."""
        repo = self._repo(params.repo)
        raw = await self._get("get_issue", f"/repos/{repo}/issues/{params.number}", {})
        if not isinstance(raw, dict):
            raise ToolError("get_issue returned something other than an issue")
        comments = await self._get(
            "get_issue",
            f"/repos/{repo}/issues/{params.number}/comments",
            {"per_page": COMMENT_LIMIT},
        )
        return IssueDetail(
            issue=_issue(raw),
            body=str(raw.get("body") or ""),
            comments=[
                Comment(
                    author=str((entry.get("user") or {}).get("login", "")),
                    body=str(entry.get("body") or ""),
                    url=str(entry.get("html_url", "")),
                )
                for entry in comments
                if isinstance(entry, dict)
            ],
        )

    async def search_issues(self, params: SearchIssuesParams) -> IssueList:
        """Issues and pull requests matching a query."""
        query = params.query.strip()
        if not query:
            raise ToolError("search_issues needs a query")
        if params.repo:
            query = f"repo:{self._repo(params.repo)} {query}"
        elif self._settings.default_owner:
            query = f"org:{self._settings.default_owner} {query}"
        raw = await self._get(
            "search_issues", "/search/issues", {"q": query, "per_page": self._settings.max_results}
        )
        if not isinstance(raw, dict):
            raise ToolError("search_issues returned something other than a result set")
        found = raw.get("items") or []
        return IssueList(issues=[_issue(entry) for entry in found if isinstance(entry, dict)])

    async def get_file(self, params: GetFileParams) -> FileContent:
        """One file from a repository, as text."""
        query = {"ref": params.ref} if params.ref else {}
        raw = await self._get(
            "get_file", f"/repos/{self._repo(params.repo)}/contents/{params.path}", query
        )
        if not isinstance(raw, dict) or raw.get("type") != "file":
            raise ToolError(f"{params.path} is not a file in that repository")
        size = int(raw.get("size", 0))
        if size > MAX_FILE_BYTES:
            raise ToolError(
                f"{params.path} is {size} bytes, over the {MAX_FILE_BYTES} the tool carries"
            )
        return FileContent(
            path=str(raw.get("path", params.path)),
            url=str(raw.get("html_url", "")),
            text=_decoded(raw),
        )

    async def create_issue(self, params: CreateIssueParams) -> Issue:
        """A new issue."""
        body: dict[str, Any] = {"title": params.title, "body": params.body}
        if params.labels:
            body["labels"] = params.labels
        raw = await self._post("create_issue", f"/repos/{self._repo(params.repo)}/issues", body)
        return _issue(raw)

    async def comment(self, params: CommentParams) -> Comment:
        """A comment added to an issue or pull request."""
        raw = await self._post(
            "comment",
            f"/repos/{self._repo(params.repo)}/issues/{params.number}/comments",
            {"body": params.body},
        )
        return Comment(
            author=str((raw.get("user") or {}).get("login", "")),
            body=str(raw.get("body") or ""),
            url=str(raw.get("html_url", "")),
        )

    def _headers(self) -> dict[str, str]:
        """What every request carries. The token never reaches a result model."""
        return {
            "Authorization": f"Bearer {self._auth.access_token.get_secret_value()}",
            "Accept": ACCEPT,
            "X-GitHub-Api-Version": VERSION,
        }

    async def _get(self, action: str, path: str, query: dict[str, Any]) -> Any:
        """One GET, parsed."""
        return await self._request(action, "GET", path, params=query)

    async def _post(self, action: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """One POST, parsed. Anything but an object is a ToolError."""
        parsed = await self._request(action, "POST", path, json=body)
        if not isinstance(parsed, dict):
            raise ToolError(f"{action} returned something other than an object")
        return parsed

    async def _request(self, action: str, method: str, path: str, **kwargs: Any) -> Any:
        """One call to the API. A transport failure or an error status is a ZipyError."""
        try:
            async with httpx.AsyncClient(
                timeout=TIMEOUT_SECS, transport=self._transport, follow_redirects=True
            ) as client:
                response = await client.request(
                    method, f"{API}{path}", headers=self._headers(), **kwargs
                )
        except httpx.HTTPError as exc:
            raise ToolError(f"{action} could not reach GitHub: {type(exc).__name__}") from exc
        if response.is_error:
            raise _failed(action, response.status_code)
        try:
            return response.json()
        except ValueError as exc:
            raise ToolError(f"{action} returned a response that is not json") from exc


def _decoded(raw: dict[str, Any]) -> str:
    """The contents of a file payload as text."""
    if raw.get("encoding") != "base64":
        return str(raw.get("content") or "")
    try:
        return base64.b64decode(str(raw.get("content") or "")).decode("utf-8", "replace")
    except (binascii.Error, ValueError) as exc:
        raise ToolError("that file is not text this tool can read") from exc
