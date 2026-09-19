"""Settings of the sandbox tool."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SandboxSettings(BaseModel):
    """[tools.sandbox] settings. Only the output limit is safe for an org to change."""

    model_config = ConfigDict(extra="forbid")

    runtime: str = "docker"
    image: str = "ghcr.io/ashworks1706/zipy-sandbox:main"
    memory: str = "256m"
    cpus: str = "1"
    pids: int = Field(default=128, gt=0)
    timeout_secs: float = Field(default=20.0, gt=0)
    max_output_chars: int = Field(default=4000, gt=0)
    session_idle_secs: float = Field(default=900.0, gt=0)
    max_sessions: int = Field(default=4, gt=0)
    workspace_mb: int = Field(default=64, gt=0)


class RunParams(BaseModel):
    """A shell command to run in the sandbox."""

    model_config = ConfigDict(extra="forbid")

    command: str
    session: str | None = None


class Output(BaseModel):
    """What the command produced."""

    model_config = ConfigDict(extra="forbid")

    exit_code: int
    stdout: str
    stderr: str
    session: str | None = None
