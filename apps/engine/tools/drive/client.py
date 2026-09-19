"""The Drive document feed, over the Google Drive API.

The tool's actions run on the Drive MCP server. This asks for every file changed since a time.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from engine.core.types import CredentialError, Document, ProviderAuth, ToolError, ZipyError
from engine.tools.drive.schemas import DriveSettings, File

FOLDER_MIME = "application/vnd.google-apps.folder"
DOCUMENT_MIME = "application/vnd.google-apps.document"
FIELDS = "nextPageToken, files(id, name, mimeType, webViewLink, modifiedTime)"
PAGE_SIZE = 100
SOURCE = "drive"

# The OAuth credential google-api-python-client sends, built from the access token alone.
_bearer: Callable[..., Any] = Credentials


def _service(auth: ProviderAuth) -> Any:
    """A Drive v3 service bound to the org's credential."""
    credentials = _bearer(token=auth.access_token.get_secret_value())
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def _failed(action: str, exc: HttpError) -> ZipyError:
    """The error the model reads. Carries the status and Google's reason, never the token."""
    status = int(getattr(exc.resp, "status", 0) or 0)
    reason = str(getattr(exc, "reason", "") or "").strip() or "the request was rejected"
    if status == 401:
        return CredentialError(f"the Google credential is expired or revoked: {reason}")
    return ToolError(f"Google Drive refused {action} with status {status}: {reason}")


async def _run(action: str, call: Callable[[], Any]) -> Any:
    """Run one blocking Google request off the event loop."""
    try:
        return await asyncio.to_thread(call)
    except HttpError as exc:
        raise _failed(action, exc) from exc


def _modified(raw: str) -> datetime:
    """The file's modification time, as an aware UTC time."""
    if not raw:
        return datetime.fromtimestamp(0, UTC)
    parsed = datetime.fromisoformat(raw)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _file(raw: dict[str, Any]) -> File:
    """One file as the model sees it."""
    return File(
        id=str(raw.get("id", "")),
        name=str(raw.get("name", "")),
        mime_type=str(raw.get("mimeType", "")),
        link=str(raw.get("webViewLink", "")),
        modified_at=_modified(str(raw.get("modifiedTime", ""))),
    )


class DriveClient:
    """Calls Drive with the org's Google credential."""

    def __init__(self, auth: ProviderAuth, settings: DriveSettings) -> None:
        self._auth = auth
        self._settings = settings

    async def documents(
        self, since: datetime | None, source_id: str = ""
    ) -> AsyncIterator[Document]:
        """Text files changed since the time, or the one named by source_id."""
        if source_id:
            request = (
                _service(self._auth)
                .files()
                .get(fileId=source_id, fields="id, name, mimeType, webViewLink, modifiedTime")
            )
            raw = await _run("documents", request.execute)
            document = await self._document(_file(raw))
            if document is not None:
                yield document
            return
        clauses = [f"mimeType != '{FOLDER_MIME}'", "trashed = false"]
        if since is not None:
            stamp = since.astimezone(UTC).isoformat().replace("+00:00", "Z")
            clauses.append(f"modifiedTime > '{stamp}'")
        for item in await self._page("documents", " and ".join(clauses), 0):
            document = await self._document(_file(item))
            if document is not None:
                yield document

    async def _page(self, action: str, query: str, limit: int) -> list[dict[str, Any]]:
        """Every raw file matching a Drive query, stopping at limit when it is set."""
        service = _service(self._auth)
        found: list[dict[str, Any]] = []
        token = ""
        while True:
            size = min(limit - len(found), PAGE_SIZE) if limit else PAGE_SIZE
            request = service.files().list(
                q=query,
                pageSize=max(size, 1),
                orderBy="modifiedTime desc",
                fields=FIELDS,
                pageToken=token or None,
                spaces="drive",
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
            )
            raw = await _run(action, request.execute)
            found.extend(raw.get("files", []))
            token = str(raw.get("nextPageToken", ""))
            if not token or (limit and len(found) >= limit):
                break
        return found[:limit] if limit else found

    async def _document(self, item: File) -> Document | None:
        """One file as a searchable document, or None when it holds no plain text."""
        text = await self._text(item)
        if not text.strip():
            return None
        return Document(
            source=SOURCE,
            source_id=item.id,
            title=item.name,
            text=text,
            updated_at=item.modified_at,
            metadata={"link": item.link, "mime_type": item.mime_type},
        )

    async def _text(self, item: File) -> str:
        """The file's plain text. Google Docs are exported; other types must be text already."""
        files = _service(self._auth).files()
        if item.mime_type == DOCUMENT_MIME:
            request = files.export(fileId=item.id, mimeType="text/plain")
        elif item.mime_type.startswith("text/"):
            request = files.get_media(fileId=item.id)
        else:
            return ""
        body = await _run("documents", request.execute)
        return body.decode("utf-8", "replace") if isinstance(body, bytes) else str(body)
