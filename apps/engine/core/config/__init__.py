"""Settings from zipy.toml and ZIPY_* env vars.

Two layers, lowest first: zipy.toml, which is committed, and ZIPY_<TABLE>__<KEY> from the
environment, which wins (ZIPY_PLATFORMS__DISCORD__TOKEN reaches [platforms.discord]).
ZIPY_CONFIG_FILE points elsewhere. Every tunable value belongs in zipy.toml at its default; secrets
and per-machine URLs live in .env. A bad combination is rejected at load. Per-org overrides are
not here; they live in Postgres and are merged by the registries.

config_version changes only when a table changes shape in a way an existing zipy.toml would
misread. A file written for another version is rejected with the version it needs.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from engine.core.config.tables import (
    Agent,
    Api,
    App,
    Budget,
    Collaboration,
    Data,
    Memory,
    ModelRole,
    Permissions,
    PlatformSettings,
    PluginSettings,
    ProviderRate,
    ProviderSettings,
    RateLimit,
    Telemetry,
    ToolSettings,
    Workers,
)
from engine.core.types.errors import ConfigError

__all__ = [
    "CONFIG_VERSION",
    "MODEL_ROLES",
    "Agent",
    "Api",
    "App",
    "Budget",
    "Collaboration",
    "Config",
    "Data",
    "Memory",
    "ModelRole",
    "Permissions",
    "PlatformSettings",
    "PluginSettings",
    "ProviderSettings",
    "ProviderRate",
    "RateLimit",
    "Telemetry",
    "ToolSettings",
    "Workers",
    "load",
]

CONFIG_VERSION = 1

# chat runs the tool loop, summary condenses transcripts and long results, embedding feeds recall.
MODEL_ROLES = ("chat", "summary", "embedding")


def _toml_files() -> tuple[Path, ...]:
    override = os.environ.get("ZIPY_CONFIG_FILE")
    return (Path(override),) if override else (Path("zipy.toml"),)


class Config(BaseSettings):
    """The whole engine configuration."""

    model_config = SettingsConfigDict(
        env_prefix="ZIPY_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
    )

    config_version: int = CONFIG_VERSION
    app: App = Field(default_factory=App)
    api: Api = Field(default_factory=Api)
    agent: Agent = Field(default_factory=Agent)
    models: dict[str, ModelRole] = {}
    memory: Memory = Field(default_factory=Memory)
    collaboration: Collaboration = Field(default_factory=Collaboration)
    budget: Budget = Field(default_factory=Budget)
    rate_limit: RateLimit = Field(default_factory=RateLimit)
    workers: Workers = Field(default_factory=Workers)
    permissions: Permissions = Field(default_factory=Permissions)
    telemetry: Telemetry = Field(default_factory=Telemetry)
    data: Data = Field(default_factory=Data)
    platforms: dict[str, PlatformSettings] = {}
    providers: dict[str, ProviderSettings] = {}
    tools: dict[str, ToolSettings] = {}

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,  # noqa: ARG003 - signature fixed by pydantic-settings
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            TomlConfigSettingsSource(settings_cls, toml_file=_toml_files()),
        )

    @model_validator(mode="after")
    def _check(self) -> Config:
        if self.config_version != CONFIG_VERSION:
            raise ConfigError(
                f"zipy.toml is config_version {self.config_version}; this Zipy reads "
                f"{CONFIG_VERSION}. See docs/ARCHITECTURE.md, Configuration."
            )
        missing = [role for role in MODEL_ROLES if role not in self.models]
        if missing:
            raise ConfigError(f"no [models.*] table for {missing}")
        if not self.models["embedding"].dimensions:
            raise ConfigError("models.embedding.dimensions must be set")
        if not any(p.enabled for p in self.platforms.values()):
            raise ConfigError("no [platforms.*] table is enabled, Zipy would receive nothing")
        for name, tool in self.tools.items():
            if not tool.actions:
                raise ConfigError(f"tools.{name}.actions is empty")
            if tool.provider and tool.provider not in self.providers:
                raise ConfigError(f"tools.{name}.provider {tool.provider} has no [providers.*]")
        if not set(self.permissions.member) <= set(self.permissions.officer):
            raise ConfigError("permissions.member may not exceed permissions.officer")
        return self

    def redacted(self) -> dict[str, object]:
        """The configuration with every secret masked, for printing."""
        shown = self.model_dump(mode="json", exclude={"platforms", "providers", "tools"})
        for kind in ("platforms", "providers", "tools"):
            tables: dict[str, PluginSettings] = getattr(self, kind)
            shown[kind] = {name: table.redacted() for name, table in tables.items()}
        return shown


@lru_cache(maxsize=1)
def load() -> Config:
    """The process-wide configuration. Cached; call load.cache_clear() in tests."""
    return Config()
