"""The sandbox tool."""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

from pydantic import BaseModel

from engine.core.types import ProviderAuth, RequestContext, SandboxRequest
from engine.tools.base import Action, BaseTool
from engine.tools.sandbox.container import ContainerSandbox, Runner
from engine.tools.sandbox.schemas import Output, RunParams, SandboxSettings

RUN = (
    "Run a shell command in a throwaway Linux container with no network access. Use it to compute, "
    "convert, inspect or reformat something rather than guessing at it. Give a session name to "
    "keep a working directory across several commands; leave it out for a one-off."
)


class SandboxTool(BaseTool[SandboxSettings]):
    """A shell in an isolated container: no network, read-only root, capped memory, CPU and time."""

    name: ClassVar[str] = "sandbox"
    provider: ClassVar[str] = ""
    owns: ClassVar[tuple[str, ...]] = ()
    settings_model: ClassVar[type[BaseModel]] = SandboxSettings
    #: Everything but the output limit decides what the container may do, so no org may set it.
    locked: ClassVar[frozenset[str]] = frozenset(
        {
            "runtime",
            "image",
            "memory",
            "cpus",
            "pids",
            "timeout_secs",
            "session_idle_secs",
            "max_sessions",
            "workspace_mb",
        }
    )
    actions: ClassVar[Mapping[str, Action]] = {
        "run": Action(RUN, RunParams, Output),
    }

    def __init__(self, settings: SandboxSettings, runner: Runner | None = None) -> None:
        super().__init__(settings)
        self._sandbox = ContainerSandbox(settings, runner)

    def target(self, action: str, params: BaseModel) -> str:  # noqa: ARG002
        """The session a command ran in, or the command itself when it kept none."""
        command = str(getattr(params, "command", ""))
        return str(getattr(params, "session", "") or "") or command[:64]

    async def execute(
        self,
        ctx: RequestContext,
        action: str,  # noqa: ARG002 - the sandbox has one action
        params: BaseModel,
        auth: ProviderAuth | None,  # noqa: ARG002 - the sandbox needs no credential
    ) -> BaseModel:
        """Run the command. A non-zero exit comes back as a result, not as an error."""
        run = RunParams.model_validate(params.model_dump())
        output = await self._sandbox.run(
            ctx, SandboxRequest(command=run.command, session=run.session)
        )
        return Output(
            exit_code=output.exit_code,
            stdout=output.stdout,
            stderr=output.stderr,
            session=output.session,
        )
