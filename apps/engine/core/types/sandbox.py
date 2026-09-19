"""What a sandboxed command is asked to do, what it produced, and the names a session takes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from engine.core.types.errors import SandboxError

#: Longest a session name may be.
MAX_SESSION_CHARS = 48

#: Longest a workspace file name may be.
MAX_FILE_CHARS = 64

#: Characters a session name takes, besides letters and digits.
SESSION_EXTRA = frozenset("-_")

#: Characters a workspace file name takes, besides letters and digits.
FILE_EXTRA = frozenset("-_.")


@dataclass(frozen=True)
class SandboxRequest:
    """A command to run in an isolated environment.

    session names the environment it runs in. A new name starts one, a running name resumes it,
    and None runs the command in a container that is removed when it exits.
    """

    command: str
    session: str | None = None


@dataclass(frozen=True)
class SandboxOutput:
    """What a sandboxed command produced. A non-zero exit is reported, not raised."""

    exit_code: int
    stdout: str
    stderr: str
    session: str | None = None


@dataclass(frozen=True)
class SandboxSession:
    """One live environment, as the reaper and the console see it."""

    name: str
    org_id: str
    member: str
    started_at: datetime
    idle_secs: float
    last_command: str = ""


def session_name(raw: str) -> str:
    """A container-safe session name. Anything else is a SandboxError."""
    name = raw.strip()
    if not 1 <= len(name) <= MAX_SESSION_CHARS:
        raise SandboxError(f"a session name is 1 to {MAX_SESSION_CHARS} characters")
    if not all(char.isascii() and (char.isalnum() or char in SESSION_EXTRA) for char in name):
        raise SandboxError("a session name takes letters, digits, hyphen and underscore")
    return name


def workspace_path(raw: str) -> str:
    """A workspace file name. A separator or a parent reference would leave the workspace."""
    name = raw.strip()
    if not 1 <= len(name) <= MAX_FILE_CHARS:
        raise SandboxError(f"a workspace name is 1 to {MAX_FILE_CHARS} characters")
    if not all(char.isascii() and (char.isalnum() or char in FILE_EXTRA) for char in name):
        raise SandboxError("a workspace name takes letters, digits, hyphen, underscore and dot")
    if name.startswith(".") or ".." in name:
        raise SandboxError("a workspace name does not start with a dot or carry two in a row")
    return name
