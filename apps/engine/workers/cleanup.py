"""Daily cleanup: expired confirmations and chunks past their retention."""

from __future__ import annotations

from engine.core.config import Memory
from engine.core.protocols import ConfirmationStore, DocumentStore


async def cleanup(
    memory: Memory, confirmations: ConfirmationStore, documents: DocumentStore
) -> None:
    """Purge expired confirmations and prune chunks older than their source's retention."""
    raise NotImplementedError
