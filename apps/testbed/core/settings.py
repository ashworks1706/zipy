"""What the training app reads from zipy.toml and ZIPY_* env vars.

The app links nothing else in the repo, so it models only the keys it reads: its own [training]
table and the trace directory the engine writes. Every other table belongs to the engine.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from testbed.core.types import TrainingError


class _Foreign(BaseModel):
    """A table owned by the engine. Only the keys this app reads are declared."""

    model_config = ConfigDict(extra="ignore")


class Telemetry(_Foreign):
    trace_dir: str = ".zipy/traces"


class Training(BaseModel):
    """Where the dataset is built and where the decisions about it live."""

    model_config = ConfigDict(extra="forbid")

    #: Generated data. Ignored by git.
    data_dir: Path = Path(".zipy/training")
    #: The review decisions, in source control.
    decisions_path: Path = Path("apps/testbed/curation/decisions.jsonl")
    #: Traces older than this are skipped by export. Zero reads every one.
    max_age_days: int = 0

    @model_validator(mode="after")
    def _check(self) -> Training:
        if self.max_age_days < 0:
            raise TrainingError("training.max_age_days cannot be negative")
        return self

    @property
    def raw_path(self) -> Path:
        """Every example the export found."""
        return self.data_dir / "raw" / "generations.jsonl"

    @property
    def verified_path(self) -> Path:
        """The well-formed, deduplicated examples a reviewer judges."""
        return self.data_dir / "processed" / "verified.jsonl"

    @property
    def training_path(self) -> Path:
        """What a training run reads. Only curated examples reach it."""
        return self.data_dir / "processed" / "sft.jsonl"

    @property
    def output_dir(self) -> Path:
        """Adapters, checkpoints and logs."""
        return self.data_dir / "outputs"


def _toml_files() -> tuple[Path, ...]:
    """Where zipy.toml is looked for. ZIPY_CONFIG_FILE overrides it."""
    override = os.environ.get("ZIPY_CONFIG_FILE")
    return (Path(override),) if override else (Path("zipy.toml"),)


class Config(BaseSettings):
    """What the training app reads."""

    model_config = SettingsConfigDict(
        env_prefix="ZIPY_", env_nested_delimiter="__", env_file=".env", extra="ignore"
    )

    training: Training = Field(default_factory=Training)
    telemetry: Telemetry = Field(default_factory=Telemetry)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,  # noqa: ARG003 - fixed by pydantic-settings
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Environment first, then .env, then zipy.toml. Earlier sources win."""
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            TomlConfigSettingsSource(settings_cls, toml_file=_toml_files()),
        )

    @property
    def traces_dir(self) -> Path:
        """Where the engine writes one JSONL file per request."""
        return Path(self.telemetry.trace_dir)


@lru_cache(maxsize=1)
def load() -> Config:
    """The configuration, read once."""
    return Config()
