"""The drive tool: its schemas, the queries it builds, and the documents it yields."""

from datetime import UTC, datetime

import pytest
from googleapiclient.errors import HttpError
from pydantic import SecretStr

from engine.core.types import CredentialError, OrgId, ProviderAuth, ToolError
from engine.tools.drive import client as client_module
from engine.tools.drive.schemas import DriveSettings, ListFolderParams, SearchFilesParams
from engine.tools.drive.tool import DriveTool

TOKEN = "ya29.a-google-access-token"
FOLDER_MIME = "application/vnd.google-apps.folder"
DOCUMENT_MIME = "application/vnd.google-apps.document"


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
    return DriveTool(DriveSettings(**settings))


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


def test_a_file_search_parses():
    assert SearchFilesParams(query="officer contact list").query == "officer contact list"


def test_drive_is_read_only():
    assert set(DriveTool.actions) == {"search_files", "list_folder"}


async def test_search_files_asks_for_name_and_content_matches(monkeypatch):
    service = google(monkeypatch, {"files.list": [{"files": [FILE]}]})

    result = await tool().execute("search_files", SearchFilesParams(query="contact list"), auth())

    name, sent = service.calls[0]
    assert name == "files.list"
    assert "name contains 'contact list'" in sent["q"]
    assert "fullText contains 'contact list'" in sent["q"]
    assert "trashed = false" in sent["q"]
    assert sent["pageSize"] == 10
    assert sent["orderBy"] == "modifiedTime desc"
    found = result.files[0]
    assert found.id == "file-1"
    assert found.name == "Officer contact list"
    assert found.modified_at.year == 2026
    assert found.link.endswith("file-1")


async def test_search_files_escapes_a_quote_in_the_query(monkeypatch):
    service = google(monkeypatch, {"files.list": [{"files": []}]})

    await tool().execute("search_files", SearchFilesParams(query="Ash's notes"), auth())

    assert "Ash\\'s notes" in service.calls[0][1]["q"]


async def test_search_files_stops_at_the_orgs_max_results(monkeypatch):
    many = [dict(FILE, id=f"file-{n}") for n in range(5)]
    google(monkeypatch, {"files.list": [{"files": many}]})

    result = await tool(max_results=2).execute(
        "search_files", SearchFilesParams(query="notes"), auth()
    )

    assert [f.id for f in result.files] == ["file-0", "file-1"]


async def test_search_files_needs_a_query(monkeypatch):
    google(monkeypatch)

    with pytest.raises(ToolError, match="needs a query"):
        await tool().execute("search_files", SearchFilesParams(query="  "), auth())


async def test_list_folder_looks_the_folder_up_by_name_then_lists_its_children(monkeypatch):
    folder = {"id": "folder-9", "name": "Events", "mimeType": FOLDER_MIME}
    service = google(monkeypatch, {"files.list": [{"files": [folder]}, {"files": [FILE]}]})

    result = await tool().execute("list_folder", ListFolderParams(folder="Events"), auth())

    lookup, children = service.calls
    assert f"mimeType = '{FOLDER_MIME}'" in lookup[1]["q"]
    assert "name = 'Events'" in lookup[1]["q"]
    assert children[1]["q"] == "'folder-9' in parents and trashed = false"
    assert [f.id for f in result.files] == ["file-1"]


async def test_list_folder_falls_back_to_treating_the_folder_as_an_id(monkeypatch):
    service = google(monkeypatch, {"files.list": [{"files": []}, {"files": []}]})

    await tool().execute("list_folder", ListFolderParams(folder="folder-9"), auth())

    assert service.calls[1][1]["q"] == "'folder-9' in parents and trashed = false"


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

    assert service.calls[0] == ("files.get", service.calls[0][1])
    assert service.calls[0][1]["fileId"] == "file-3"
    assert found[0].text == "budget notes"


async def test_a_google_refusal_becomes_a_tool_error_naming_the_reason(monkeypatch):
    google(monkeypatch, error=http_error(403, "Insufficient Permission"))

    with pytest.raises(ToolError) as caught:
        await tool().execute("search_files", SearchFilesParams(query="notes"), auth())

    assert "403" in str(caught.value)
    assert "Insufficient Permission" in str(caught.value)


async def test_an_expired_token_becomes_a_credential_error(monkeypatch):
    google(monkeypatch, error=http_error(401, "Invalid Credentials"))

    with pytest.raises(CredentialError, match="expired or revoked"):
        await tool().execute("search_files", SearchFilesParams(query="notes"), auth())


async def test_a_tool_without_the_orgs_google_account_refuses_to_run():
    with pytest.raises(CredentialError, match="google is not connected"):
        await tool().execute("search_files", SearchFilesParams(query="notes"), None)

    with pytest.raises(CredentialError, match="google is not connected"):
        await tool().execute("search_files", SearchFilesParams(query="notes"), auth("notion"))


async def test_the_token_reaches_neither_a_result_nor_an_error(monkeypatch):
    google(monkeypatch, {"files.list": [{"files": [FILE]}]})
    result = await tool().execute("search_files", SearchFilesParams(query="notes"), auth())
    assert TOKEN not in result.model_dump_json()

    google(monkeypatch, error=http_error(401, "Invalid Credentials"))
    with pytest.raises(CredentialError) as caught:
        await tool().execute("search_files", SearchFilesParams(query="notes"), auth())
    assert TOKEN not in str(caught.value)
