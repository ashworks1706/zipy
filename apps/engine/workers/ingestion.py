"""Document sync for every tool that syncs, on its interval or when a webhook job arrives.

Job kinds are sync:<tool> for a periodic sync of one org and document:<tool> for one document
named in the payload. Neither needs code here for a new tool.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from engine.core.config import Memory
from engine.core.protocols import CredentialStore, DocumentStore, Embedder
from engine.core.types import CredentialError, IngestError, Job, ProviderAuth
from engine.memory.ingest.pipeline import ingest
from engine.telemetry.logging import get
from engine.tools.base import BaseTool
from engine.tools.registry import Registry

log = get("engine.workers.ingestion")

SYNC = "sync"
DOCUMENT = "document"


def sync_job(tool: str) -> str:
    """The job kind of a periodic sync of one tool."""
    return f"sync:{tool}"


def document_job(tool: str) -> str:
    """The job kind of one document of one tool."""
    return f"document:{tool}"


def _since(payload: dict[str, Any]) -> datetime | None:
    """The time a sync job asks for documents changed after, or None for every document."""
    raw = payload.get("since")
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    try:
        return datetime.fromisoformat(str(raw))
    except ValueError as exc:
        raise IngestError(f"job payload since is not a timestamp: {raw!r}") from exc


class Ingestion:
    """Runs sync and document jobs through the tool's documents() and the memory pipeline."""

    def __init__(
        self,
        registry: Registry,
        memory: Memory,
        credentials: CredentialStore,
        embedder: Embedder,
        documents: DocumentStore,
    ) -> None:
        self._registry = registry
        self._memory = memory
        self._credentials = credentials
        self._embedder = embedder
        self._documents = documents

    async def run(self, job: Job) -> None:
        """Fetch the job's documents from the tool and replace their chunks."""
        kind, _, name = job.kind.partition(":")
        if kind not in (SYNC, DOCUMENT) or not name:
            raise IngestError(f"unknown job kind {job.kind}")
        tool = self._tool(name)
        source_id = str(job.payload.get("source_id", "")) if kind == DOCUMENT else ""
        if kind == DOCUMENT and not source_id:
            raise IngestError(f"{job.kind} has no source_id in its payload")
        since = _since(job.payload) if kind == SYNC else None
        auth = await self._auth(job, type(tool))
        stored = 0
        seen = 0
        async for document in tool.documents(auth, since, source_id):
            seen += 1
            stored += await ingest(
                job.org_id, document, self._memory, self._embedder, self._documents
            )
        log.info(
            "documents ingested",
            kind=job.kind,
            org_id=str(job.org_id),
            documents=seen,
            chunks=stored,
        )

    def _tool(self, name: str) -> BaseTool[Any]:
        """The syncing tool a job names, built from zipy.toml."""
        if name not in self._registry.syncing():
            raise IngestError(f"tool {name} is not an enabled tool that syncs documents")
        cls = self._registry.tool_class(name)
        return cls(self._registry.settings_for(name))

    async def _auth(self, job: Job, cls: type[BaseTool[Any]]) -> ProviderAuth | None:
        """The org's credential for the tool's provider, or None for a tool that needs none."""
        if not cls.provider:
            return None
        auth = await self._credentials.get(job.org_id, cls.provider)
        if auth is None:
            raise CredentialError(f"{cls.provider} is not connected for org {job.org_id}")
        return auth
