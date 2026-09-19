"""Cleanup: expired confirmations, chunks past their retention, and idle sandbox sessions."""

from __future__ import annotations

from datetime import timedelta

from engine.core.config import Memory
from engine.core.protocols import ConfirmationStore, DocumentStore, Sandbox
from engine.telemetry.logging import get
from engine.workers.scheduler import now_utc

log = get("engine.workers.cleanup")


async def cleanup(
    memory: Memory, confirmations: ConfirmationStore, documents: DocumentStore
) -> None:
    """Purge expired confirmations and prune chunks older than their source's retention."""
    moment = now_utc()
    dropped = await confirmations.purge_expired(moment)
    pruned = 0
    for source, days in memory.retention_days.items():
        pruned += await documents.prune(source, moment - timedelta(days=days))
    log.info("cleanup swept", confirmations=dropped, chunks=pruned)


async def reap_sandboxes(sandbox: Sandbox) -> None:
    """Remove every sandbox session idle past its budget."""
    gone = await sandbox.reap_idle()
    if gone:
        log.info("sandbox sessions reaped", count=len(gone))
