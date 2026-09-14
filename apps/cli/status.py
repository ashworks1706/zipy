"""What the status bar shows: platforms, the engine's health, traces, services, git, the box."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from cli.core.config import Config


@dataclass(frozen=True)
class Machine:
    """What the metrics pane shows about the box itself."""

    load: float
    cpus: int
    mem_used_gib: float
    mem_total_gib: float


@dataclass(frozen=True)
class Snapshot:
    """Everything the status bar shows, gathered at one moment."""

    platforms: tuple[str, ...]
    engine_up: bool
    traces: int
    last_trace: str
    git: str
    # Each compose service that exists, by name: running, starting, unhealthy or restarting.
    services: Mapping[str, str] = field(default_factory=dict)
    machine: Machine | None = None


def machine() -> Machine | None:
    """Load and memory from the kernel, or None where they cannot be read."""
    try:
        fields = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            fields[key] = float(rest.split()[0]) / (1024 * 1024)
        total, free = fields["MemTotal"], fields["MemAvailable"]
        return Machine(os.getloadavg()[0], os.cpu_count() or 1, max(total - free, 0.0), total)
    except (OSError, ValueError, KeyError, IndexError):
        return None


def git_sha() -> str:
    """The working tree's commit, with -dirty appended when it has changes."""

    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], text=True, stderr=subprocess.DEVNULL).strip()

    try:
        sha = git("rev-parse", "--short", "HEAD")
        return f"{sha}-dirty" if git("status", "--porcelain") else sha
    except (subprocess.CalledProcessError, OSError):
        return "unknown"


def traces(directory: Path) -> tuple[int, str]:
    """How many request traces exist, and the newest one's request id and time."""
    files = list(directory.glob("*/*.jsonl"))
    if not files:
        return 0, ""
    newest = max(files, key=lambda f: f.stat().st_mtime)
    try:
        last = json.loads(newest.read_text(encoding="utf-8").splitlines()[-1])
        return len(files), f"{newest.stem[:8]} {str(last.get('at', ''))[11:19]}"
    except (OSError, IndexError, json.JSONDecodeError):
        return len(files), newest.stem[:8]


def engine_up(cfg: Config) -> bool:
    """Whether zipy serve answers its health route."""
    url = f"http://{cfg.api.host}:{cfg.api.port}/health"
    try:
        with urllib.request.urlopen(url, timeout=1) as response:  # noqa: S310 - loopback only
            return bool(response.status == 200)
    except OSError:
        return False


def parse_compose_ps(out: str) -> dict[str, str]:
    """docker compose ps --format json, as service -> running, starting, unhealthy or restarting.

    A container that is up but whose healthcheck has not passed yet is starting, not running.
    Compose writes one object per line, or one array, depending on its version.
    """
    try:
        rows = (
            json.loads(out)
            if out.lstrip().startswith("[")
            else [json.loads(line) for line in out.splitlines() if line.strip()]
        )
    except json.JSONDecodeError:
        return {}
    states = {}
    for row in rows:
        name, state, health = row.get("Service"), row.get("State"), row.get("Health") or ""
        if not name:
            continue
        if state == "running":
            states[name] = "running" if health in ("", "healthy") else health
        elif state in ("restarting", "removing", "paused"):
            states[name] = "restarting"
    return states


def compose_services(compose: Path = Path("deploy/compose.yml")) -> dict[str, str]:
    """What each compose service is doing. Empty when docker is absent or fails."""
    if shutil.which("docker") is None or not compose.exists():
        return {}
    try:
        out = subprocess.run(
            ["docker", "compose", "-f", str(compose), "--profile", "*", "ps", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return {}
    return parse_compose_ps(out)


def snapshot(cfg: Config) -> Snapshot:
    """The status bar's view of the repo, read from disk, the engine and docker compose."""
    count, last = traces(Path(cfg.telemetry.trace_dir)) if cfg.telemetry.trace_dir else (0, "")
    return Snapshot(
        platforms=tuple(cfg.enabled_platforms),
        engine_up=engine_up(cfg),
        traces=count,
        last_trace=last,
        git=git_sha(),
        services=compose_services(),
        machine=machine(),
    )
