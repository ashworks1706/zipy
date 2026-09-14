"""Document sync for every tool that syncs, on its interval or when a webhook job arrives.

Job kinds are sync:<tool> for a periodic sync of one org and document:<tool> for one document
named in the payload. Neither needs code here for a new tool.
"""

from __future__ import annotations

from engine.core.config import Memory
from engine.core.protocols import CredentialStore, DocumentStore, Embedder
from engine.core.types import Job
from engine.tools.registry import Registry


def sync_job(tool: str) -> str:
    """The job kind of a periodic sync of one tool."""
    return f"sync:{tool}"


def document_job(tool: str) -> str:
    """The job kind of one document of one tool."""
    return f"document:{tool}"


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
        raise NotImplementedError
