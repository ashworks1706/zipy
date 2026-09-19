"""The drive document feed: the queries it builds and the documents it yields.

The tool's actions run on the Drive MCP server; tests/test_remote.py covers them.
"""

from datetime import UTC, datetime

import pytest
from googleapiclient.errors import HttpError
from pydantic import SecretStr

from engine.core.types import CredentialError, Document, OrgId, ProviderAuth, ToolError
from engine.tools.drive import client as client_module
from engine.tools.drive.schemas import DriveSettings
from engine.tools.drive.tool import DriveTool

TOKEN = "ya29.a-google-access-token"
FOLDER_MIME = "application/vnd.google-apps.folder"
DOCUMENT_MIME = "application/vnd.google-apps.document"
ENDPOINT = "https://drivemcp.googleapis.com/mcp/v1"


class FakeRequest:
    """One prepared Google request that records itself when executed."""

    def __init__(self, service, name, kwargs):
        self._service = service
        self._name = name
        self._kwargs = kwargs

    def execute(self):
        self._service.calls.append((self._name, self._kwargs))
        if self._service.error is not None:
            raise self._service.error
        return self._service.answer(self._name)


class FakeCollection:
    """The files collection of the fake service."""

    def __init__(self, service, prefix):
        self._service = service
        self._prefix = prefix

    def __getattr__(self, method):
        def prepare(**kwargs):
            return FakeRequest(self._service, f"{self._prefix}.{method}", kwargs)

        return prepare


class FakeService:
    """A stand-in for the discovery-built Google service. Answers are consumed in order."""

    def __init__(self, results=None, error=None):
        self.calls = []
        self.error = error
        self._results = {k: list(v) for k, v in (results or {}).items()}

    def answer(self, name):
        queued = self._results.get(name)
        if not queued:
            return {}
        return queued.pop(0) if len(queued) > 1 else queued[0]

    def files(self):
        return FakeCollection(self, "files")


def google(monkeypatch, results=None, error=None):
    """Put a fake Google service behind the client and return it."""
    service = FakeService(results, error)
    monkeypatch.setattr(client_module, "build", lambda *args, **kwargs: service)
    return service


def auth(provider="google"):
    return ProviderAuth(
        org_id=OrgId("org-1"),
        provider=provider,
        access_token=SecretStr(TOKEN),
        scopes=("https://www.googleapis.com/auth/drive.readonly",),
        expires_at=None,
    )


def tool(**settings):
    return DriveTool(DriveSettings(endpoint=ENDPOINT, **settings))


def http_error(status, message):
    class Response:
        def __init__(self):
            self.status = status
            self.reason = message

    body = f'{{"error": {{"code": {status}, "message": "{message}"}}}}'.encode()
    return HttpError(Response(), body, uri="https://www.googleapis.com/drive/v3/files")


FILE = {
    "id": "file-1",
    "name": "Officer contact list",
    "mimeType": DOCUMENT_MIME,
    "webViewLink": "https://docs.google.com/document/d/file-1",
    "modifiedTime": "2026-09-14T17:30:00.000Z",
}


def test_drive_reads_and_never_writes():
    assert set(DriveTool.actions) == {
        "search_files",
        "list_recent_files",
        "get_file_metadata",
        "read_file_content",
    }


async def test_documents_exports_google_docs_and_skips_what_has_no_text(monkeypatch):
    binary = dict(FILE, id="file-2", name="Poster", mimeType="image/png")
    service = google(
        monkeypatch,
        {"files.list": [{"files": [FILE, binary]}], "files.export": [b"Ash is president.\n"]},
    )

    found = [doc async for doc in tool().documents(auth(), None)]

    assert [call[0] for call in service.calls] == ["files.list", "files.export"]
    assert len(found) == 1
    assert found[0].source == "drive"
    assert found[0].source_id == "file-1"
    assert found[0].title == "Officer contact list"
    assert found[0].text == "Ash is president.\n"
    assert found[0].metadata["link"].endswith("file-1")


async def test_documents_since_a_time_asks_google_for_the_changed_files_only(monkeypatch):
    service = google(monkeypatch, {"files.list": [{"files": []}]})

    assert [doc async for doc in tool().documents(auth(), datetime(2026, 9, 1, tzinfo=UTC))] == []
    assert "modifiedTime > '2026-09-01T00:00:00Z'" in service.calls[0][1]["q"]


async def test_documents_for_one_file_fetches_that_file(monkeypatch):
    text_file = dict(FILE, id="file-3", mimeType="text/plain")
    service = google(monkeypatch, {"files.get": [text_file], "files.get_media": [b"budget notes"]})

    found = [doc async for doc in tool().documents(auth(), None, "file-3")]

    assert service.calls[0][0] == "files.get"
    assert service.calls[0][1]["fileId"] == "file-3"
    assert found[0].text == "budget notes"


async def test_a_google_refusal_becomes_a_tool_error_naming_the_reason(monkeypatch):
    google(monkeypatch, error=http_error(403, "Insufficient Permission"))

    with pytest.raises(ToolError) as caught:
        [doc async for doc in tool().documents(auth(), None)]

    assert "403" in str(caught.value)
    assert "Insufficient Permission" in str(caught.value)


async def test_an_expired_token_becomes_a_credential_error(monkeypatch):
    google(monkeypatch, error=http_error(401, "Invalid Credentials"))

    with pytest.raises(CredentialError, match="expired or revoked"):
        [doc async for doc in tool().documents(auth(), None)]


async def test_a_feed_without_the_orgs_google_account_refuses_to_run():
    with pytest.raises(CredentialError, match="google is not connected"):
        tool().documents(None, None)

    with pytest.raises(CredentialError, match="google is not connected"):
        tool().documents(auth("notion"), None)


async def test_the_token_reaches_neither_a_document_nor_an_error(monkeypatch):
    google(monkeypatch, {"files.list": [{"files": [FILE]}], "files.export": [b"text"]})
    found: list[Document] = [doc async for doc in tool().documents(auth(), None)]
    assert TOKEN not in repr(found[0])

    google(monkeypatch, error=http_error(401, "Invalid Credentials"))
    with pytest.raises(CredentialError) as caught:
        [doc async for doc in tool().documents(auth(), None)]
    assert TOKEN not in str(caught.value)
