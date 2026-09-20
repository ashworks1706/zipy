"""Training examples from the engine's trace files.

The engine writes one JSONL file per request, and a generation event in it carries the messages
sent to the provider and the reply that came back. That is a training example already, so the
export reads the traces rather than a telemetry service.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from testbed.core.types import TrainingExample

#: The trace event a training example is made from.
EVENT = "generation"


def _at(raw: str) -> datetime | None:
    """One event timestamp, or None when it cannot be read."""
    try:
        return datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None


def _example(record: dict[str, Any], index: int) -> TrainingExample | None:
    """One generation event as an example. An event of another kind is None."""
    if record.get("event") != EVENT:
        return None
    data = record.get("data") or {}
    messages = data.get("input")
    if not isinstance(messages, list):
        return None
    return TrainingExample(
        id=f"{record.get('request_id', '')}:{index}",
        messages=messages,
        reply=str(data.get("output") or ""),
        tool_calls=[call for call in data.get("tool_calls") or [] if isinstance(call, dict)],
        model=str(data.get("model") or ""),
        org_id=str(record.get("org_id") or ""),
        platform=str(record.get("platform") or ""),
        at=_at(str(record.get("at", ""))),
    )


def from_trace(path: Path) -> list[TrainingExample]:
    """Every generation in one request's trace, numbered by the order it happened in."""
    examples = []
    index = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        example = _example(record, index)
        if example is not None:
            examples.append(example)
            index += 1
    return examples


def traces(directory: Path, max_age_days: int = 0) -> Iterator[Path]:
    """Every trace file under the directory, newest first. Zero days reads every one."""
    cutoff = datetime.now(UTC) - timedelta(days=max_age_days) if max_age_days else None
    found = sorted(directory.glob("*/*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in found:
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        if cutoff is not None and modified < cutoff:
            return
        yield path


def export(directory: Path, max_age_days: int = 0) -> list[TrainingExample]:
    """Every example the traces under a directory hold."""
    return [example for path in traces(directory, max_age_days) for example in from_trace(path)]
