"""One pydantic model per zipy.toml table. Each rejects an unknown key and a bad value.

Plugin tables ([platforms.*], [providers.*], [tools.*]) accept any key: keys other than the ones
declared here belong to the plugin and are validated by its own settings model when it loads.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, SecretStr, model_validator

from engine.core.types.chat import ActionType
from engine.core.types.collaboration import IMPLEMENTED, Conditioning
from engine.core.types.errors import ConfigError
from engine.core.types.identity import Role

SECRET_SUFFIXES = ("secret", "token", "key", "password", "dsn")


class _Table(BaseModel):
    model_config = ConfigDict(extra="forbid")


class App(_Table):
    """Process-wide settings."""

    env: str = "dev"
    name: str = "Zipy"

    @model_validator(mode="after")
    def _check(self) -> App:
        if self.env not in ("dev", "prod"):
            raise ConfigError("app.env must be dev or prod")
        return self


class Api(_Table):
    """The HTTP server for OAuth callbacks, webhooks and platform events. public_url is in .env."""

    host: str = "127.0.0.1"
    port: int = 8080
    public_url: str = "http://127.0.0.1:8080"

    @model_validator(mode="after")
    def _check(self) -> Api:
        if not 0 < self.port < 65536:
            raise ConfigError("api.port must be a TCP port")
        return self


class Agent(_Table):
    """The tool-calling loop."""

    max_iterations: int = 8
    confirmation_ttl_secs: int = 120
    system_template: str = "system.md.j2"
    #: Images of one message sent to the model. 0 sends none.
    max_images: int = 4

    @model_validator(mode="after")
    def _check(self) -> Agent:
        if self.max_iterations < 1:
            raise ConfigError("agent.max_iterations must be at least 1")
        if self.confirmation_ttl_secs < 10:
            raise ConfigError("agent.confirmation_ttl_secs must be at least 10")
        return self


class ModelRole(_Table):
    """One model the engine uses for one job, as a LiteLLM model string. api_key is in .env."""

    model: str
    api_key: SecretStr = SecretStr("")
    api_base: str = ""
    fallbacks: list[str] = []
    temperature: float = 0.2
    max_tokens: int = 1024
    timeout_secs: float = 60.0
    dimensions: int = 0
    # What this endpoint can be conditioned with. An endpoint that takes only tokens is text.
    conditioning: Conditioning = Conditioning.TEXT

    @model_validator(mode="after")
    def _check(self) -> ModelRole:
        if not 0 <= self.temperature <= 2:
            raise ConfigError("models.*.temperature must lie in [0, 2]")
        if self.max_tokens < 1 or self.timeout_secs <= 0:
            raise ConfigError("models.*.max_tokens and timeout_secs must be positive")
        if self.conditioning not in IMPLEMENTED:
            built = ", ".join(c.value for c in IMPLEMENTED)
            raise ConfigError(
                f"models.*.conditioning {self.conditioning.value} has no renderer yet; "
                f"built so far: {built}"
            )
        return self


class Files(_Table):
    """Files attached to a message, read into text and stored for recall."""

    enabled: bool = True
    # Files read from one message. The rest are named and left.
    max_per_message: int = 5
    max_bytes: int = 20_000_000
    # Characters one file yields. A larger file is read up to here, not refused.
    max_chars: int = 200_000
    # Characters of the reading that go into this turn's prompt. The whole of it stays searchable.
    max_prompt_chars: int = 8_000
    download_timeout_secs: float = 30.0
    parse_timeout_secs: float = 30.0

    @model_validator(mode="after")
    def _check(self) -> Files:
        if self.max_per_message < 1:
            raise ConfigError("files.max_per_message must be at least 1")
        if self.max_bytes < 1 or self.max_chars < 1:
            raise ConfigError("files.max_bytes and max_chars must be positive")
        if self.max_prompt_chars > self.max_chars:
            raise ConfigError("files.max_prompt_chars cannot exceed files.max_chars")
        if self.download_timeout_secs <= 0 or self.parse_timeout_secs <= 0:
            raise ConfigError("files.download_timeout_secs and parse_timeout_secs must be positive")
        return self


class Collaboration(_Table):
    """Per-person collaboration state. Off means every prompt is what it would be without it."""

    enabled: bool = False
    alpha: float = 0.15
    min_observations: int = 5
    # Phrases that read a follow-up turn. Only a turn right after an answer is read at all.
    brevity_triggers: list[str] = []
    detail_triggers: list[str] = []
    correction_triggers: list[str] = []

    @model_validator(mode="after")
    def _check(self) -> Collaboration:
        if not 0 < self.alpha <= 1:
            raise ConfigError("collaboration.alpha must lie in (0, 1]")
        if self.min_observations < 1:
            raise ConfigError("collaboration.min_observations must be at least 1")
        return self


class Memory(_Table):
    """Conversation history, semantic recall and chunking."""

    conversation_limit: int = 20
    recall_triggers: list[str] = []
    recall_top_k: int = 5
    recall_min_similarity: float = 0.72
    chunk_tokens: int = 500
    chunk_overlap_tokens: int = 50
    retention_days: dict[str, int] = {}

    @model_validator(mode="after")
    def _check(self) -> Memory:
        if not 0 <= self.conversation_limit <= 100:
            raise ConfigError("memory.conversation_limit must lie in [0, 100]")
        if not 0 < self.recall_min_similarity <= 1:
            raise ConfigError("memory.recall_min_similarity must lie in (0, 1]")
        if self.chunk_overlap_tokens >= self.chunk_tokens:
            raise ConfigError("memory.chunk_overlap_tokens must be less than chunk_tokens")
        return self


class Budget(_Table):
    """The default monthly model spend per org."""

    monthly_cents: int = 200


class ProviderRate(_Table):
    """Calls one org may make to one provider."""

    per_minute: int = 60
    burst: int = 10

    @model_validator(mode="after")
    def _check(self) -> ProviderRate:
        if self.per_minute <= 0:
            raise ConfigError("a provider rate per_minute must be above 0")
        if self.burst < 1:
            raise ConfigError("a provider rate burst must be at least 1")
        return self


class RateLimit(_Table):
    """Message rate per member, and outbound call rate per org and provider."""

    per_member_per_minute: int = 10
    provider: ProviderRate = ProviderRate()
    providers: dict[str, ProviderRate] = {}
    provider_max_wait_seconds: float = 5.0

    def for_provider(self, provider: str) -> ProviderRate:
        """The rate for one provider, its own when it has one."""
        return self.providers.get(provider, self.provider)

    @model_validator(mode="after")
    def _check(self) -> RateLimit:
        if self.per_member_per_minute <= 0:
            raise ConfigError("rate_limit.per_member_per_minute must be above 0")
        if self.provider_max_wait_seconds < 0:
            raise ConfigError("rate_limit.provider_max_wait_seconds must not be negative")
        return self


class Workers(_Table):
    """Background job intervals. Per-tool sync intervals live in each [tools.*] table."""

    token_refresh_minutes: int = 45
    token_refresh_window_minutes: int = 60
    cleanup_hour_utc: int = 4

    @model_validator(mode="after")
    def _check(self) -> Workers:
        if self.token_refresh_window_minutes <= self.token_refresh_minutes:
            raise ConfigError(
                "workers.token_refresh_window_minutes must exceed token_refresh_minutes"
            )
        if not 0 <= self.cleanup_hour_utc < 24:
            raise ConfigError("workers.cleanup_hour_utc must lie in [0, 23]")
        return self


class Permissions(_Table):
    """The action types each role may run by default."""

    admin: list[ActionType] = list(ActionType)
    officer: list[ActionType] = list(ActionType)
    member: list[ActionType] = [ActionType.READ]

    def allowed(self, role: Role) -> frozenset[ActionType]:
        """The action types a role may run by default."""
        return frozenset(getattr(self, role.value))


class Telemetry(_Table):
    """Logs, trace files, metrics, Sentry and LangFuse. The DSN and keys are in .env.

    trace_dir receives one JSONL file per request; empty writes none. metrics serves /metrics on
    the API. An empty DSN or LangFuse key sends nothing there.
    """

    service_name: str = "zipy"
    log_json: bool = False
    trace_dir: str = ".zipy/traces"
    metrics: bool = True
    sentry_dsn: SecretStr = SecretStr("")
    sentry_traces_sample_rate: float = 0.1
    langfuse_host: str = ""
    langfuse_public_key: SecretStr = SecretStr("")
    langfuse_secret_key: SecretStr = SecretStr("")


class Data(_Table):
    """Postgres, Redis and the credential key. All are in .env."""

    database_url: SecretStr = SecretStr("")
    redis_url: SecretStr = SecretStr("")
    fernet_key: SecretStr = SecretStr("")


class PluginSettings(BaseModel):
    """A plugin table. Keys not declared here are the plugin's own settings."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = True

    @property
    def options(self) -> dict[str, object]:
        """The plugin's own settings."""
        return dict(self.model_extra or {})

    def redacted(self) -> dict[str, object]:
        """The table with every secret-looking plugin setting masked."""
        shown: dict[str, object] = {"enabled": self.enabled}
        for key, value in self.options.items():
            secret = key.lower().endswith(SECRET_SUFFIXES) and value
            shown[key] = "**********" if secret else value
        return shown


class PlatformSettings(PluginSettings):
    """A [platforms.name] table: a chat platform Zipy lives on."""


class ProviderSettings(PluginSettings):
    """A [providers.name] table: an account type orgs connect, such as google or notion."""


class ToolSettings(PluginSettings):
    """A [tools.name] table. provider is empty for a tool that needs no connected account."""

    provider: str = ""
    scopes: list[str] = []
    actions: dict[str, ActionType]

    def redacted(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "scopes": self.scopes,
            "actions": {k: v.value for k, v in self.actions.items()},
            **super().redacted(),
        }
