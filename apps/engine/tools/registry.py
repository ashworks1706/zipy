"""Discovers tool plugins, checks them against zipy.toml, and offers an org its tools.

A tool is offered when its provider is connected (or it needs none) and it is enabled, by the
org's override if there is one and by zipy.toml otherwise. A plugin without a table, a table
without a plugin, a provider mismatch, or an action declared on one side only fails at startup.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ValidationError

from engine.core.config import ToolSettings
from engine.core.plugins import discover, match
from engine.core.types import ActionType, ConfigError, OrgToolConfig, from_wire
from engine.tools.base import BaseTool, function_schema

ToolClass = type[BaseTool[Any]]


class Registry:
    """The tool plugins, checked against their [tools.*] tables."""

    def __init__(
        self, tables: Mapping[str, ToolSettings], classes: Mapping[str, ToolClass] | None = None
    ) -> None:
        self._tables = dict(tables)
        self._classes = dict(
            discover("engine.tools", "tool", BaseTool) if classes is None else classes
        )
        match("tools", self._classes, self._tables)
        for name, cls in self._classes.items():
            table = self._tables[name]
            if table.provider != cls.provider:
                raise ConfigError(f"tools.{name}.provider must be {cls.provider or 'empty'}")
            declared = sorted(set(cls.actions) ^ set(table.actions))
            if declared:
                raise ConfigError(f"tools.{name}.actions differ from the plugin: {declared}")
            self.settings_for(name)

    @property
    def names(self) -> list[str]:
        """Every tool name, sorted."""
        return sorted(self._classes)

    def tool_class(self, name: str) -> ToolClass:
        """The class of one tool."""
        return self._classes[name]

    def syncing(self) -> list[str]:
        """Every enabled tool that produces searchable documents, sorted."""
        return sorted(n for n, c in self._classes.items() if c.syncs and self._tables[n].enabled)

    def action_type(self, qualified_name: str) -> ActionType:
        """The type zipy.toml gives an action. An unknown action is a ConfigError."""
        tool, _, action = qualified_name.partition(".")
        table = self._tables.get(tool)
        if table is None or action not in table.actions:
            raise ConfigError(f"unknown tool action {qualified_name}")
        return table.actions[action]

    def settings_for(self, name: str, override: OrgToolConfig | None = None) -> BaseModel:
        """The tool's settings: zipy.toml, with the org's overrides merged over it."""
        cls: ToolClass = self._classes[name]
        merged = {**self._tables[name].options, **(override.overrides if override else {})}
        try:
            settings: BaseModel = cls.settings_model.model_validate(merged)
        except ValidationError as exc:
            raise ConfigError(f"tools.{name} settings are invalid: {exc}") from exc
        return settings

    def available(
        self, connected: frozenset[str], overrides: Mapping[str, OrgToolConfig]
    ) -> list[str]:
        """The tools one org may be offered, sorted."""
        offered = []
        for name, cls in self._classes.items():
            override = overrides.get(name)
            enabled = override.enabled if override else self._tables[name].enabled
            if enabled and (not cls.provider or cls.provider in connected):
                offered.append(name)
        return sorted(offered)

    def schemas(self, names: list[str]) -> list[dict[str, Any]]:
        """The function-calling schemas of every action of the named tools."""
        return [
            function_schema(name, action_name, action)
            for name in names
            for action_name, action in self._classes[name].actions.items()
        ]

    def resolve(self, function_name: str) -> tuple[str, str]:
        """The tool and action a function name from the model refers to."""
        tool, _, action = from_wire(function_name).partition(".")
        if tool not in self._classes or action not in self._classes[tool].actions:
            raise ConfigError(f"the model called an unknown function {function_name}")
        return tool, action
