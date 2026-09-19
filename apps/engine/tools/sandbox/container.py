"""A command in a container: no network, read-only root, capped resources, non-root user.

The engine holds no session map. Every session container carries labels naming the org, the
member and the session, and the workspace holds a marker file touched on each use, so listing,
reaping and the per-member cap all read the runtime rather than process memory. A restarted
engine sees the sessions it left behind instead of leaking them.
"""

from __future__ import annotations

import asyncio
import hashlib
import shlex
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from engine.core.types import (
    MemberRef,
    OrgId,
    RequestContext,
    SandboxError,
    SandboxOutput,
    SandboxRequest,
    SandboxSession,
    session_name,
    workspace_path,
)
from engine.telemetry.logging import get
from engine.tools.sandbox.schemas import SandboxSettings

log = get("engine.tools.sandbox")

#: Where the writable workspace is mounted inside the container.
WORKSPACE = "/tmp"

#: The file whose modification time says when the session was last used.
MARKER = f"{WORKSPACE}/.zipy-used"

#: The label every sandbox container carries.
OWNED = "zipy.sandbox=1"

#: What the reaper and the console read back from a container.
FORMAT = (
    "{{.Name}}\t{{.Config.Labels.zipy_org}}\t{{.Config.Labels.zipy_member}}\t{{.State.StartedAt}}"
)


@dataclass(frozen=True)
class Completed:
    """What running one runtime command produced."""

    code: int
    stdout: str
    stderr: str


#: Runs one process and returns what it produced. Replaced in tests.
Runner = Callable[[Sequence[str], bytes | None, float], Awaitable[Completed]]


async def run_process(args: Sequence[str], stdin: bytes | None, timeout: float) -> Completed:
    """Run one process to completion, killing it at the timeout."""
    process = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(process.communicate(stdin), timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise
    return Completed(
        code=process.returncode if process.returncode is not None else -1,
        stdout=out.decode("utf-8", "replace"),
        stderr=err.decode("utf-8", "replace"),
    )


def clip(text: str, limit: int) -> str:
    """The head and the tail of text, naming what was dropped between them."""
    if limit <= 0 or len(text) <= limit:
        return text
    head = (limit + 1) // 2
    tail = limit - head
    dropped = len(text) - limit
    return f"{text[:head]}\n[{dropped} characters cut]\n{text[len(text) - tail :]}"


def owner(org_id: OrgId, member: MemberRef) -> str:
    """The prefix every session container of one member shares."""
    parts = f"{org_id}\0{member.platform}\0{member.user_id}"
    return f"zipy-sb-{hashlib.sha256(parts.encode()).hexdigest()[:16]}-"


def _parsed(line: str, now: datetime) -> SandboxSession | None:
    """One inspect line as a session. A line the runtime did not fill is skipped."""
    parts = line.split("\t")
    if len(parts) != 4:
        return None
    name, org, member, started = parts
    try:
        at = datetime.fromisoformat(started.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return SandboxSession(
        name=name.strip().lstrip("/"),
        org_id=org.strip(),
        member=member.strip(),
        started_at=at,
        idle_secs=max((now - at).total_seconds(), 0.0),
    )


class ContainerSandbox:
    """Runs commands in a container. Holds settings and nothing else."""

    def __init__(self, settings: SandboxSettings, runner: Runner | None = None) -> None:
        self._settings = settings
        self._run_process = runner or run_process

    async def probe(self) -> None:
        """Check the runtime answers. A failure is a SandboxError naming the runtime."""
        done = await self._runtime(["version", "--format", "{{.Server.Version}}"])
        if done.code != 0:
            raise SandboxError(
                f"{self._settings.runtime} did not answer: {done.stderr.strip() or 'no reason'}"
            )

    async def run(self, ctx: RequestContext, request: SandboxRequest) -> SandboxOutput:
        """Run one command, in a session or in a container removed when it exits."""
        command = request.command.strip()
        if not command:
            raise SandboxError("the command is empty")
        if request.session is None:
            done = await self._runtime([*self._throwaway(), "sh", "-c", command])
            return self._output(done, None)
        session = session_name(request.session)
        container = await self._started(ctx, session)
        done = await self._runtime(
            ["exec", "--workdir", WORKSPACE, container, "sh", "-c", self._marked(command)]
        )
        return self._output(done, session)

    async def put(self, ctx: RequestContext, session: str, name: str, content: bytes) -> str:
        """Write bytes into a session workspace and return the path they landed at."""
        wanted = session_name(session)
        file = workspace_path(name)
        container = await self._started(ctx, wanted)
        path = f"{WORKSPACE}/{file}"
        done = await self._runtime(
            [
                "exec",
                "--interactive",
                "--workdir",
                WORKSPACE,
                container,
                "sh",
                "-c",
                self._marked(f"cat > {shlex.quote(path)}"),
            ],
            stdin=content,
        )
        if done.code != 0:
            raise SandboxError(f"could not write {file}: {done.stderr.strip() or 'no reason'}")
        return path

    async def sessions(self, org_id: OrgId | None = None) -> list[SandboxSession]:
        """Every live session, newest first, with how long each has been idle."""
        listed = await self._runtime(["ps", "--quiet", "--filter", f"label={OWNED}"])
        ids = [line for line in listed.stdout.split() if line]
        if not ids:
            return []
        shown = await self._runtime(["inspect", "--format", FORMAT, *ids])
        now = datetime.now(UTC)
        found = []
        for line in shown.stdout.splitlines():
            session = _parsed(line, now)
            if session is None or (org_id is not None and session.org_id != org_id):
                continue
            idle = await self._idle(session.name, now)
            found.append(session if idle is None else replace(session, idle_secs=idle))
        return sorted(found, key=lambda s: s.started_at, reverse=True)

    async def kill(self, name: str) -> bool:
        """Tear one session down now. False when there was nothing of that name."""
        done = await self._runtime(["rm", "--force", name])
        return done.code == 0

    async def reap_idle(self) -> list[str]:
        """Remove every session idle past its budget and name the ones that went."""
        budget = self._settings.session_idle_secs
        gone = []
        for session in await self.sessions():
            if session.idle_secs >= budget and await self.kill(session.name):
                log.debug("sandbox session reaped", session=session.name)
                gone.append(session.name)
        return gone

    def _output(self, done: Completed, session: str | None) -> SandboxOutput:
        """What the model reads, with each stream cut to max_output_chars."""
        limit = self._settings.max_output_chars
        return SandboxOutput(
            exit_code=done.code,
            stdout=clip(done.stdout, limit),
            stderr=clip(done.stderr, limit),
            session=session,
        )

    def _marked(self, command: str) -> str:
        """The command, after noting that the session was used."""
        return f"touch {MARKER} 2>/dev/null; {command}"

    async def _idle(self, name: str, now: datetime) -> float | None:
        """Seconds since the session was last used, or None when the marker is unreadable."""
        done = await self._runtime(
            ["exec", name, "sh", "-c", f"stat -c %Y {MARKER} 2>/dev/null || echo"]
        )
        stamp = done.stdout.strip()
        if done.code != 0 or not stamp.isdigit():
            return None
        return max(now.timestamp() - float(stamp), 0.0)

    async def _started(self, ctx: RequestContext, session: str) -> str:
        """The container of a session, started if it was not already running."""
        container = f"{owner(ctx.org_id, ctx.member)}{session}"
        if await self._running(container):
            return container
        await self.kill(container)
        await self._within_cap(ctx)
        done = await self._runtime(
            [
                "run",
                "--detach",
                "--name",
                container,
                *self._labels(ctx),
                *self._seal(),
                self._settings.image,
                "sleep",
                "infinity",
            ]
        )
        # Another request started the same session between the check and here.
        if done.code != 0 and "already in use" not in done.stderr:
            raise SandboxError(f"could not start the session: {done.stderr.strip() or 'no reason'}")
        return container

    async def _within_cap(self, ctx: RequestContext) -> None:
        """Reap the member's oldest session when they already hold the most they may."""
        prefix = owner(ctx.org_id, ctx.member)
        held = [s for s in await self.sessions() if s.name.startswith(prefix)]
        over = len(held) - max(self._settings.max_sessions, 1) + 1
        if over <= 0:
            return
        for session in sorted(held, key=lambda s: s.idle_secs, reverse=True)[:over]:
            await self.kill(session.name)

    async def _running(self, name: str) -> bool:
        """Whether a container of this name exists and is running."""
        done = await self._runtime(["inspect", "--format", "{{.State.Running}}", name])
        return done.code == 0 and done.stdout.strip() == "true"

    def _labels(self, ctx: RequestContext) -> list[str]:
        """The labels that make the runtime the session registry."""
        return [
            "--label",
            OWNED,
            "--label",
            f"zipy_org={ctx.org_id}",
            "--label",
            f"zipy_member={ctx.member.platform}:{ctx.member.user_id}",
        ]

    def _seal(self) -> list[str]:
        """The arguments that seal a container."""
        settings = self._settings
        return [
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            "65534:65534",
            "--memory",
            settings.memory,
            "--cpus",
            settings.cpus,
            "--pids-limit",
            str(settings.pids),
            "--tmpfs",
            f"{WORKSPACE}:rw,noexec,nosuid,size={settings.workspace_mb}m",
            "--workdir",
            WORKSPACE,
        ]

    def _throwaway(self) -> list[str]:
        """The arguments for a call that keeps no session."""
        return ["run", "--rm", *self._seal(), self._settings.image]

    async def _runtime(self, args: Sequence[str], stdin: bytes | None = None) -> Completed:
        """One runtime call. A timeout and a runtime that will not start are SandboxErrors."""
        try:
            return await self._run_process(
                [self._settings.runtime, *args], stdin, self._settings.timeout_secs
            )
        except TimeoutError as exc:
            raise SandboxError(
                f"the command ran past its {self._settings.timeout_secs} second budget"
            ) from exc
        except OSError as exc:
            raise SandboxError(f"{self._settings.runtime} did not start: {exc}") from exc
