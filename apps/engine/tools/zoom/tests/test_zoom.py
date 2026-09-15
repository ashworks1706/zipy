"""The zoom tool: its schemas, the requests it builds, and the transcripts it returns."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import SecretStr

from engine.core.types import CredentialError, OrgId, ProviderAuth, ToolError
from engine.tools.zoom import tool as tool_module
from engine.tools.zoom.client import ZoomClient
from engine.tools.zoom.schemas import LatestSummaryParams, ListRecordingsParams, ZoomSettings
from engine.tools.zoom.tool import ZoomTool

TOKEN = "zoom-oauth-access-token"
VTT = """WEBVTT

1
00:00:01.000 --> 00:00:04.000
Ash: We approved the sponsorship.

2
00:00:05.000 --> 00:00:08.000
Maria: I will email them.
"""

EXEC = {
    "uuid": "abc==",
    "id": 123,
    "topic": "Exec Board",
    "start_time": "2026-09-10T17:00:00Z",
    "recording_files": [
        {"file_type": "TRANSCRIPT", "download_url": "https://zoom.us/rec/download/t1"}
    ],
}
SOCIAL = {
    "uuid": "def==",
    "id": 124,
    "topic": "Social Committee",
    "start_time": "2026-09-12T17:00:00Z",
    "recording_files": [{"file_type": "MP4", "download_url": "https://zoom.us/rec/download/m1"}],
}


class Zoom:
    """A stand-in Zoom API. Routes are matched by the part of the url they name."""

    def __init__(self, routes, failure=None):
        self.requests = []
        self._routes = {key: list(value) for key, value in routes.items()}
        self._failure = failure

    def handle(self, request):
        self.requests.append(request)
        if self._failure is not None:
            raise self._failure
        for key, answers in self._routes.items():
            if key in str(request.url):
                status, body = answers.pop(0) if len(answers) > 1 else answers[0]
                if isinstance(body, str):
                    return httpx.Response(status, text=body)
                return httpx.Response(status, json=body)
        return httpx.Response(404, json={"message": "no such route"})


def zoom(monkeypatch, routes=None, failure=None):
    """Put a stand-in Zoom API behind the tool and return it."""
    api = Zoom(routes or {}, failure)
    transport = httpx.MockTransport(api.handle)
    monkeypatch.setattr(
        tool_module,
        "ZoomClient",
        lambda auth, settings: ZoomClient(auth, settings, transport=transport),
    )
    return api


def auth(provider="zoom"):
    return ProviderAuth(
        org_id=OrgId("org-1"),
        provider=provider,
        access_token=SecretStr(TOKEN),
        scopes=("cloud_recording:read",),
        expires_at=None,
    )


def tool():
    return ZoomTool(ZoomSettings())


def recently():
    return datetime.now(UTC) - timedelta(days=5)


def sent_to(api, part):
    """Every request the client made whose url names that part of the API."""
    return [request for request in api.requests if part in str(request.url)]


def test_latest_summary_needs_no_topic():
    assert LatestSummaryParams().topic == ""


async def test_list_recordings_asks_for_the_window_and_answers_newest_first(monkeypatch):
    api = zoom(monkeypatch, {"/users/me/recordings": [(200, {"meetings": [EXEC, SOCIAL]})]})
    since = recently()

    result = await tool().execute("list_recordings", ListRecordingsParams(since=since), auth())

    sent = api.requests[0]
    assert sent.url.params["from"] == since.date().isoformat()
    assert sent.url.params["page_size"] == "30"
    assert sent.headers["Authorization"] == f"Bearer {TOKEN}"
    assert [r.topic for r in result.recordings] == ["Social Committee", "Exec Board"]
    assert result.recordings[1].has_transcript is True
    assert result.recordings[0].has_transcript is False
    assert result.recordings[1].meeting_id == "abc=="


async def test_list_recordings_follows_zooms_page_token(monkeypatch):
    api = zoom(
        monkeypatch,
        {
            "/users/me/recordings": [
                (200, {"meetings": [SOCIAL], "next_page_token": "page-2"}),
                (200, {"meetings": [EXEC]}),
            ]
        },
    )

    result = await tool().execute("list_recordings", ListRecordingsParams(since=recently()), auth())

    assert api.requests[1].url.params["next_page_token"] == "page-2"
    assert len(result.recordings) == 2


async def test_latest_summary_downloads_the_newest_matching_transcript(monkeypatch):
    api = zoom(
        monkeypatch,
        {
            "/users/me/recordings": [(200, {"meetings": [EXEC, SOCIAL]})],
            "/meetings/": [(200, EXEC)],
            "/rec/download/": [(200, VTT)],
        },
    )

    result = await tool().execute("latest_summary", LatestSummaryParams(topic="exec"), auth())

    assert "abc" in str(sent_to(api, "/meetings/")[0].url)
    assert sent_to(api, "/rec/download/")[0].headers["Authorization"] == f"Bearer {TOKEN}"
    assert result.recording.topic == "Exec Board"
    assert result.text == "Ash: We approved the sponsorship.\nMaria: I will email them."


async def test_latest_summary_says_when_no_recording_matches(monkeypatch):
    zoom(monkeypatch, {"/users/me/recordings": [(200, {"meetings": [SOCIAL]})]})

    with pytest.raises(ToolError, match="about budget"):
        await tool().execute("latest_summary", LatestSummaryParams(topic="budget"), auth())


async def test_a_recording_without_a_transcript_file_says_so(monkeypatch):
    zoom(
        monkeypatch,
        {
            "/users/me/recordings": [(200, {"meetings": [EXEC]})],
            "/meetings/": [(200, SOCIAL)],
        },
    )

    with pytest.raises(ToolError, match="has no transcript"):
        await tool().execute("latest_summary", LatestSummaryParams(), auth())


async def test_a_meeting_uuid_holding_a_slash_is_escaped_twice(monkeypatch):
    odd = dict(EXEC, uuid="/abc//d==")
    api = zoom(
        monkeypatch,
        {
            "/users/me/recordings": [(200, {"meetings": [odd]})],
            "/meetings/": [(200, odd)],
            "/rec/download/": [(200, VTT)],
        },
    )

    await tool().execute("latest_summary", LatestSummaryParams(), auth())

    assert "%252F" in str(sent_to(api, "/meetings/")[0].url)


async def test_documents_yields_a_document_for_every_transcript(monkeypatch):
    zoom(
        monkeypatch,
        {
            "/users/me/recordings": [(200, {"meetings": [EXEC, SOCIAL]})],
            "/meetings/": [(200, EXEC)],
            "/rec/download/": [(200, VTT)],
        },
    )

    found = [doc async for doc in tool().documents(auth(), recently())]

    assert len(found) == 1
    assert found[0].source == "zoom"
    assert found[0].source_id == "abc=="
    assert found[0].title == "Exec Board"
    assert found[0].text.startswith("Ash:")
    assert found[0].updated_at == datetime(2026, 9, 10, 17, tzinfo=UTC)


async def test_a_zoom_refusal_becomes_a_tool_error_naming_the_message(monkeypatch):
    zoom(monkeypatch, {"/users/me/recordings": [(429, {"message": "Too many requests"})]})

    with pytest.raises(ToolError) as caught:
        await tool().execute("list_recordings", ListRecordingsParams(since=recently()), auth())

    assert "429" in str(caught.value)
    assert "Too many requests" in str(caught.value)


async def test_an_expired_token_becomes_a_credential_error(monkeypatch):
    zoom(monkeypatch, {"/users/me/recordings": [(401, {"message": "Access token is expired"})]})

    with pytest.raises(CredentialError, match="expired or revoked"):
        await tool().execute("list_recordings", ListRecordingsParams(since=recently()), auth())


async def test_a_zoom_that_does_not_answer_becomes_a_tool_error(monkeypatch):
    zoom(monkeypatch, failure=httpx.ConnectError("no route to host"))

    with pytest.raises(ToolError, match="did not answer"):
        await tool().execute("list_recordings", ListRecordingsParams(since=recently()), auth())


async def test_a_tool_without_the_orgs_zoom_account_refuses_to_run():
    params = ListRecordingsParams(since=recently())

    with pytest.raises(CredentialError, match="zoom is not connected"):
        await tool().execute("list_recordings", params, None)

    with pytest.raises(CredentialError, match="zoom is not connected"):
        await tool().execute("list_recordings", params, auth(provider="google"))


async def test_the_token_reaches_neither_a_result_nor_an_error(monkeypatch):
    zoom(monkeypatch, {"/users/me/recordings": [(200, {"meetings": [EXEC]})]})
    params = ListRecordingsParams(since=recently())
    result = await tool().execute("list_recordings", params, auth())
    assert TOKEN not in result.model_dump_json()

    zoom(monkeypatch, {"/users/me/recordings": [(401, {"message": "Access token is expired"})]})
    with pytest.raises(CredentialError) as caught:
        await tool().execute("list_recordings", params, auth())
    assert TOKEN not in str(caught.value)
