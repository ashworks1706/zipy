"""Tools that answer from a file instead of a provider.

An eval must be the same run every time, so no case reaches Google, Notion or Zoom. Each real tool
class is subclassed with its execute replaced: the fixture for the action is validated into the
result model the plugin declares, so a fixture that no longer fits the schema fails the run rather
than passing quietly.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError
from pydantic import SecretStr as Secret

from engine.core.types import ConfigError, OrgId, ProviderAuth, ToolError
from engine.tools.base import BaseTool, qualified
from engine.tools.registry import Registry

#: What a provider the fixtures stand in for looks like to the executor.
TOKEN = Secret("fixture-token-not-a-secret")


def replayed(cls: type[BaseTool[Any]], answers: dict[str, dict[str, Any]]) -> type[BaseTool[Any]]:
    """One tool class whose actions answer from the fixtures rather than its provider."""

    class Replayed(cls):  # type: ignore[valid-type, misc]
        """The same tool, reading its answers from evals/fixtures.toml."""

        async def execute(
            self,
            action: str,
            params: BaseModel,  # noqa: ARG002 - the fixture is the same whatever was asked
            auth: ProviderAuth | None,  # noqa: ARG002 - a fixture needs no credential
        ) -> BaseModel:
            name = qualified(cls.name, action)
            if name not in answers:
                raise ToolError(f"no fixture for {name} in evals/fixtures.toml")
            result = cls.actions[action].result
            try:
                return result.model_validate(answers[name])
            except ValidationError as exc:
                raise ConfigError(f"the fixture for {name} is not a {result.__name__}") from exc

    Replayed.__name__ = f"Replayed{cls.__name__}"
    return Replayed


def classes(
    registry: Registry, answers: dict[str, dict[str, Any]]
) -> dict[str, type[BaseTool[Any]]]:
    """Every tool the registry knows, replaced by the one that replays fixtures."""
    return {name: replayed(registry.tool_class(name), answers) for name in registry.names}


def auths(org_id: OrgId, registry: Registry) -> dict[tuple[OrgId, str], ProviderAuth]:
    """A connected credential per provider a tool needs, so the executor lets the call through."""
    providers = {registry.tool_class(name).provider for name in registry.names}
    return {
        (org_id, provider): ProviderAuth(
            org_id=org_id,
            provider=provider,
            access_token=TOKEN,
            scopes=(),
            expires_at=None,
        )
        for provider in sorted(providers)
        if provider
    }


def load(path: Path) -> dict[str, Any]:
    """Everything evals/fixtures.toml holds: the org, its facts, and one table per action."""
    return tomllib.loads(path.read_text(encoding="utf-8"))
