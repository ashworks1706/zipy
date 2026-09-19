"""BaseTool: what every tool plugin implements, and the naming of its actions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar

from pydantic import BaseModel

from engine.core.types import CredentialError, Document, ProviderAuth, wire_name


@dataclass(frozen=True)
class Action:
    """One action a tool exposes. Its type comes from zipy.toml, not from here.

    parameters is the schema the model is shown when it is not the params model's own, which is
    how a remote tool passes on the schema its server published.
    """

    description: str
    params: type[BaseModel]
    result: type[BaseModel]
    parameters: dict[str, Any] | None = None


class BaseTool[S: BaseModel](ABC):
    """One integration. name matches its folder and its [tools.name] table.

    provider names the [providers.*] account the tool needs, or is empty. owns lists the
    third-party libraries only this plugin may import. syncs is true when documents() yields
    searchable documents for semantic recall. locked names settings an org may not override,
    which is every setting that decides where a credential is sent.
    """

    name: ClassVar[str]
    provider: ClassVar[str] = ""
    owns: ClassVar[tuple[str, ...]] = ()
    syncs: ClassVar[bool] = False
    locked: ClassVar[frozenset[str]] = frozenset()
    settings_model: ClassVar[type[BaseModel]]
    actions: ClassVar[Mapping[str, Action]]

    def __init__(self, settings: S) -> None:
        self.settings = settings

    @abstractmethod
    async def execute(self, action: str, params: BaseModel, auth: ProviderAuth | None) -> BaseModel:
        """Run one action with validated params. Provider failures raise ToolError."""

    def target(self, action: str, params: BaseModel) -> str:  # noqa: ARG002 - overridable hook
        """What the action acts on, for the audit log and the confirmation prompt."""
        return ""

    def documents(
        self,
        auth: ProviderAuth | None,  # noqa: ARG002 - overridable hook
        since: datetime | None,  # noqa: ARG002 - overridable hook
        source_id: str = "",  # noqa: ARG002 - overridable hook
    ) -> AsyncIterator[Document]:
        """Documents changed since a time, or the one named by source_id. Only when syncs."""
        raise NotImplementedError


def first_set(params: BaseModel, *names: str) -> str:
    """The first of the named fields carrying a value, as text. Empty when none does."""
    for name in names:
        value = getattr(params, name, None)
        if value:
            return str(value)
    return ""


def qualified(tool: str, action: str) -> str:
    """The name the orchestrator, audit log and zipy.toml use: calendar.create_event."""
    return f"{tool}.{action}"


def require_auth(auth: ProviderAuth | None, provider: str) -> ProviderAuth:
    """The credential, or CredentialError when the org has not connected the provider."""
    if auth is None or auth.provider != provider:
        raise CredentialError(f"{provider} is not connected")
    return auth


def function_schema(tool: str, action_name: str, action: Action) -> dict[str, Any]:
    """The function-calling schema of one action."""
    return {
        "type": "function",
        "function": {
            "name": wire_name(qualified(tool, action_name)),
            "description": action.description,
            "parameters": action.parameters or action.params.model_json_schema(),
        },
    }
