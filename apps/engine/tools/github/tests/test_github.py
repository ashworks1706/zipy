"""The github tool: its schemas, the calls it makes, and what it makes of the answers."""

import base64
import json

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from engine.core.types import CredentialError, OrgId, ProviderAuth, ToolError
from engine.tools.github.client import MAX_FILE_BYTES, GithubClient
from engine.tools.github.schemas import (
    CommentParams,
    CreateIssueParams,
    GetFileParams,
    GetIssueParams,
    GithubSettings,
    ListIssuesParams,
    SearchIssuesParams,
)
from engine.tools.github.tool import GithubTool

TOKEN = "gho_a-github-token-value"

ISSUE = {
    "number": 14,
    "title": "Add eval suite",
    "state": "open",
    "html_url": "https://github.com/soda/zipy/issues/14",
    "user": {"login": "ash"},
    "labels": [{"name": "enhancement"}],
    "body": "the body",
    "updated_at": "2026-09-18T03:00:00Z",
}

PULL = {**ISSUE, "number": 15, "pull_request": {"url": "x"}}


def auth(provider="github"):
    return ProviderAuth(
        org_id=OrgId("org-1"),
        provider=provider,
        access_token=SecretStr(TOKEN),
        scopes=("repo",),
        expires_at=None,
    )


class Api:
    """A GitHub that answers from a routing table and records what it was asked."""

    def __init__(self, routes, status=200):
        self.routes = routes
        self.status = status
        self.calls = []

    def handle(self, request):
        self.calls.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={"message": "no"})
        for path, body in self.routes.items():
            if request.url.path == path:
                return httpx.Response(200, json=body)
        return httpx.Response(404, json={"message": "not found"})


def client(routes, status=200, **settings):
    api = Api(routes, status)
    return (
        GithubClient(auth(), GithubSettings(**settings), transport=httpx.MockTransport(api.handle)),
        api,
    )


# ---------------------------------------------------------------- schemas


def test_every_params_model_refuses_a_key_it_does_not_declare():
    with pytest.raises(ValidationError):
        ListIssuesParams(repo="soda/zipy", token=TOKEN)


def test_params_parse_the_requests_the_user_stories_ask():
    assert ListIssuesParams(repo="zipy").state == "open"
    assert GetIssueParams(repo="soda/zipy", number=14).number == 14
    assert SearchIssuesParams(query="flaky test").repo == ""
    assert GetFileParams(repo="soda/zipy", path="README.md").ref == ""
    assert CreateIssueParams(repo="zipy", title="Fix the gate").body == ""
    assert CommentParams(repo="zipy", number=14, body="on it").number == 14


# ---------------------------------------------------------------- reading


async def test_listing_issues_carries_the_fields_an_answer_needs():
    reader, api = client({"/repos/soda/zipy/issues": [ISSUE, PULL]})

    found = await reader.list_issues(ListIssuesParams(repo="soda/zipy"))

    assert [i.number for i in found.issues] == [14, 15]
    assert found.issues[0].author == "ash"
    assert found.issues[0].labels == ["enhancement"]
    assert found.issues[0].is_pull_request is False
    assert found.issues[1].is_pull_request is True


async def test_a_bare_repo_name_is_read_under_the_default_owner():
    reader, api = client({"/repos/soda/zipy/issues": [ISSUE]}, default_owner="soda")

    await reader.list_issues(ListIssuesParams(repo="zipy"))

    assert api.calls[0].url.path == "/repos/soda/zipy/issues"


def test_a_bare_repo_name_with_no_default_owner_says_so():
    reader, _ = client({})
    with pytest.raises(ToolError, match="owner/name"):
        reader._repo("zipy")


async def test_labels_are_sent_as_the_api_wants_them():
    reader, api = client({"/repos/soda/zipy/issues": [ISSUE]})

    await reader.list_issues(ListIssuesParams(repo="soda/zipy", labels=["bug", "ci"]))

    assert api.calls[0].url.params["labels"] == "bug,ci"


async def test_one_issue_comes_back_with_its_conversation():
    reader, _ = client(
        {
            "/repos/soda/zipy/issues/14": ISSUE,
            "/repos/soda/zipy/issues/14/comments": [
                {"user": {"login": "maria"}, "body": "looks right", "html_url": "u"}
            ],
        }
    )

    found = await reader.get_issue(GetIssueParams(repo="soda/zipy", number=14))

    assert found.body == "the body"
    assert [c.author for c in found.comments] == ["maria"]


async def test_a_search_is_scoped_to_the_repo_when_one_is_named():
    reader, api = client({"/search/issues": {"items": [ISSUE]}})

    await reader.search_issues(SearchIssuesParams(query="flaky", repo="soda/zipy"))

    assert api.calls[0].url.params["q"] == "repo:soda/zipy flaky"


async def test_a_search_falls_back_to_the_org_when_no_repo_is_named():
    reader, api = client({"/search/issues": {"items": []}}, default_owner="soda")

    await reader.search_issues(SearchIssuesParams(query="flaky"))

    assert api.calls[0].url.params["q"] == "org:soda flaky"


async def test_a_search_with_no_query_is_refused_before_the_call():
    reader, api = client({"/search/issues": {"items": []}})
    with pytest.raises(ToolError, match="needs a query"):
        await reader.search_issues(SearchIssuesParams(query="   "))
    assert api.calls == []


async def test_a_file_comes_back_decoded():
    content = base64.b64encode(b"# Zipy\n").decode()
    reader, _ = client(
        {
            "/repos/soda/zipy/contents/README.md": {
                "type": "file",
                "path": "README.md",
                "html_url": "u",
                "size": 7,
                "encoding": "base64",
                "content": content,
            }
        }
    )

    found = await reader.get_file(GetFileParams(repo="soda/zipy", path="README.md"))

    assert found.text == "# Zipy\n"


async def test_a_directory_is_not_a_file():
    reader, _ = client({"/repos/soda/zipy/contents/apps": {"type": "dir"}})
    with pytest.raises(ToolError, match="not a file"):
        await reader.get_file(GetFileParams(repo="soda/zipy", path="apps"))


async def test_a_file_too_big_to_carry_is_refused_rather_than_cut():
    reader, _ = client(
        {
            "/repos/soda/zipy/contents/big.bin": {
                "type": "file",
                "path": "big.bin",
                "size": MAX_FILE_BYTES + 1,
                "encoding": "base64",
                "content": "",
            }
        }
    )
    with pytest.raises(ToolError, match="over the"):
        await reader.get_file(GetFileParams(repo="soda/zipy", path="big.bin"))


# ---------------------------------------------------------------- writing


async def test_opening_an_issue_sends_the_title_and_body():
    reader, api = client({"/repos/soda/zipy/issues": ISSUE})

    made = await reader.create_issue(
        CreateIssueParams(repo="soda/zipy", title="Fix the gate", labels=["ci"])
    )

    sent = json.loads(api.calls[0].content)
    assert api.calls[0].method == "POST"
    assert sent["title"] == "Fix the gate"
    assert sent["labels"] == ["ci"]
    assert made.number == 14


async def test_a_comment_comes_back_as_what_was_posted():
    reader, _ = client(
        {
            "/repos/soda/zipy/issues/14/comments": {
                "user": {"login": "zipy"},
                "body": "on it",
                "html_url": "u",
            }
        }
    )

    made = await reader.comment(CommentParams(repo="soda/zipy", number=14, body="on it"))

    assert made.author == "zipy"
    assert made.body == "on it"


# ---------------------------------------------------------------- failures


async def test_a_refused_credential_is_a_credential_error_not_a_tool_error():
    reader, _ = client({}, status=401)
    with pytest.raises(CredentialError):
        await reader.list_issues(ListIssuesParams(repo="soda/zipy"))


async def test_a_missing_repository_says_what_was_not_found():
    reader, _ = client({}, status=404)
    with pytest.raises(ToolError, match="found nothing"):
        await reader.list_issues(ListIssuesParams(repo="soda/ghost"))


async def test_a_server_failure_carries_the_status_and_never_the_token():
    reader, _ = client({}, status=500)
    with pytest.raises(ToolError) as raised:
        await reader.list_issues(ListIssuesParams(repo="soda/zipy"))
    assert "500" in str(raised.value)
    assert TOKEN not in str(raised.value)


async def test_the_token_goes_in_the_header_and_nowhere_else():
    reader, api = client({"/repos/soda/zipy/issues": [ISSUE]})

    found = await reader.list_issues(ListIssuesParams(repo="soda/zipy"))

    assert api.calls[0].headers["authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in found.model_dump_json()


# ---------------------------------------------------------------- the tool


def test_the_tool_needs_its_own_provider():
    from engine.core.types import CredentialError as Missing

    tool = GithubTool(GithubSettings())
    with pytest.raises(Missing):
        import asyncio

        asyncio.run(tool.execute("list_issues", ListIssuesParams(repo="soda/zipy"), auth("google")))


def test_the_target_names_what_an_action_touches():
    tool = GithubTool(GithubSettings())
    assert tool.target("get_issue", GetIssueParams(repo="soda/zipy", number=14)) == "soda/zipy#14"
    assert tool.target("list_issues", ListIssuesParams(repo="soda/zipy")) == "soda/zipy"
    assert tool.target("search_issues", SearchIssuesParams(query="flaky")) == "flaky"


def test_every_action_the_class_declares_has_a_handler():
    tool = GithubTool(GithubSettings())
    assert set(tool.actions) == {
        "list_issues",
        "get_issue",
        "search_issues",
        "get_file",
        "create_issue",
        "comment",
    }
