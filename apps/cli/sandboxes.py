"""The sandbox sessions the engine has open, read from the container runtime.

The engine keeps no session map: it labels every sandbox container and the runtime is the
registry. That is why the console can read them without talking to the engine, and still see them
when the engine is down.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

#: The label the engine puts on every sandbox container.
OWNED = "zipy.sandbox=1"

#: What one container reports back, in the order the format asks for it.
FORMAT = (
    "{{.Name}}\t{{.Config.Labels.zipy_org}}\t{{.Config.Labels.zipy_member}}\t{{.State.StartedAt}}"
)

#: Seconds a runtime call may take before the console gives up on it.
TIMEOUT = 5.0

#: Processes shown for one session. A session running more than this is doing something odd.
MAX_PROCESSES = 8

#: Runs one runtime command and returns its stdout, or "" when it did not run.
Reader = Callable[[Sequence[str]], str]


@dataclass(frozen=True)
class Session:
    """One live sandbox session and what is running in it."""

    name: str
    org_id: str
    member: str
    started_at: datetime
    processes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def age_secs(self) -> float:
        return max((datetime.now(UTC) - self.started_at).total_seconds(), 0.0)

    @property
    def busy(self) -> bool:
        """Whether anything but the session's own idle process is running."""
        return bool(self.processes)


def read(args: Sequence[str]) -> str:
    """Run one runtime command. A runtime that is not there is no sessions, not a crash."""
    try:
        done = subprocess.run(
            list(args), capture_output=True, text=True, timeout=TIMEOUT, check=False
        )
    except (subprocess.SubprocessError, OSError):
        return ""
    return done.stdout if done.returncode == 0 else ""


def _at(raw: str) -> datetime | None:
    try:
        return datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _processes(name: str, runtime: str, reader: Reader) -> tuple[str, ...]:
    """What is running inside one session, without the shell that holds it open."""
    out = reader([runtime, "top", name, "-eo", "args"])
    lines = [line.strip() for line in out.splitlines()[1:] if line.strip()]
    running = [line for line in lines if not line.startswith("sleep")]
    return tuple(running[:MAX_PROCESSES])


def live(runtime: str = "docker", reader: Reader = read) -> list[Session]:
    """Every sandbox session the runtime has, newest first."""
    listed = reader([runtime, "ps", "--quiet", "--filter", f"label={OWNED}"])
    ids = [line for line in listed.split() if line]
    if not ids:
        return []
    shown = reader([runtime, "inspect", "--format", FORMAT, *ids])
    found = []
    for line in shown.splitlines():
        parts = line.split("\t")
        if len(parts) != 4:
            continue
        name, org, member, started = parts
        at = _at(started)
        if at is None:
            continue
        clean = name.strip().lstrip("/")
        found.append(
            Session(
                name=clean,
                org_id=org.strip(),
                member=member.strip(),
                started_at=at,
                processes=_processes(clean, runtime, reader),
            )
        )
    return sorted(found, key=lambda s: s.started_at, reverse=True)


def kill(name: str, runtime: str = "docker", reader: Reader = read) -> bool:
    """Tear one session down now."""
    return bool(reader([runtime, "rm", "--force", name]).strip())


def kill_all(runtime: str = "docker", reader: Reader = read) -> int:
    """Tear every sandbox session down and say how many went."""
    sessions = live(runtime, reader)
    return sum(1 for session in sessions if kill(session.name, runtime, reader))
