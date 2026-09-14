"""Discovers provider plugins and checks them against [providers.*]."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from engine.auth.providers.base import BaseProvider
from engine.core.config import ProviderSettings
from engine.core.plugins import discover, match
from engine.core.types import ConfigError

ProviderClass = type[BaseProvider[Any]]


class Providers:
    """The enabled providers, built with their settings."""

    def __init__(
        self,
        tables: Mapping[str, ProviderSettings],
        public_url: str,
        classes: Mapping[str, ProviderClass] | None = None,
    ) -> None:
        found = dict(
            discover(__package__ or "", "provider", BaseProvider) if classes is None else classes
        )
        match("providers", found, tables)
        self.classes = found
        self._built: dict[str, BaseProvider[Any]] = {}
        for name, cls in found.items():
            if not tables[name].enabled:
                continue
            try:
                settings = cls.settings_model.model_validate(tables[name].options)
            except ValidationError as exc:
                raise ConfigError(f"providers.{name} settings are invalid: {exc}") from exc
            redirect = f"{public_url.rstrip('/')}/auth/{name}/callback"
            self._built[name] = cls(settings, redirect)

    def get(self, name: str) -> BaseProvider[Any]:
        """One enabled provider. Unknown or disabled is a ConfigError."""
        if name not in self._built:
            raise ConfigError(f"provider {name} is not enabled")
        return self._built[name]

    @property
    def enabled(self) -> list[str]:
        """Every enabled provider name, sorted."""
        return sorted(self._built)
