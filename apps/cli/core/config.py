"""The settings the console reads from zipy.toml and ZIPY_* env vars.

The console links nothing in the repo, so it models only the keys it reads: its own [console]
table, and the platforms and trace directory the status bar reports. Every other table belongs to
the engine and is ignored here.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)


class ConfigError(Exception):
    """A console setting is out of range."""


class _Foreign(BaseModel):
    """A table owned by the engine. Only the keys the console reads are declared."""

    model_config = ConfigDict(extra="ignore")


class Platform(_Foreign):
    enabled: bool = False


class Telemetry(_Foreign):
    trace_dir: str = ".zipy/traces"


class Api(_Foreign):
    host: str = "127.0.0.1"
    port: int = 8080


class Sandbox(_Foreign):
    """[tools.sandbox], for the console's view of the sessions the engine has open."""

    enabled: bool = False
    runtime: str = "docker"


class Console(BaseModel):
    """The developer console. Every line a unit prints is also appended under log_dir."""

    model_config = ConfigDict(extra="forbid")

    log_lines: int = 5000
    log_dir: Path = Path(".zipy/logs")
    splash: bool = True
    status_interval_secs: float = 5.0
    metrics_interval_secs: float = 2.0

    @model_validator(mode="after")
    def _check(self) -> Console:
        if self.log_lines <= 0:
            raise ConfigError("console.log_lines must be positive")
        if self.status_interval_secs <= 0:
            raise ConfigError("console.status_interval_secs must be positive")
        if self.metrics_interval_secs <= 0:
            raise ConfigError("console.metrics_interval_secs must be positive")
        return self


def _toml_files() -> tuple[Path, ...]:
    override = os.environ.get("ZIPY_CONFIG_FILE")
    return (Path(override),) if override else (Path("zipy.toml"),)


class Config(BaseSettings):
    """What the console reads."""

    model_config = SettingsConfigDict(
        env_prefix="ZIPY_", env_nested_delimiter="__", env_file=".env", extra="ignore"
    )

    console: Console = Field(default_factory=Console)
    platforms: dict[str, Platform] = {}
    telemetry: Telemetry = Field(default_factory=Telemetry)
    api: Api = Field(default_factory=Api)
    tools: dict[str, Sandbox] = {}

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

    @property
    def sandbox(self) -> Sandbox:
        """The sandbox table, at its defaults when zipy.toml has none."""
        return self.tools.get("sandbox", Sandbox())

    @property
    def enabled_platforms(self) -> list[str]:
        """Every platform zipy serve would run, sorted."""
        return sorted(name for name, table in self.platforms.items() if table.enabled)
