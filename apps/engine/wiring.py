"""The composition root: builds every dependency from config and runs the process.

Platforms, the HTTP server and the scheduler share one event loop. Trace events fan out to the
JSONL files under telemetry.trace_dir, LangFuse, and the local platform when it runs.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import uvicorn
from fastapi import APIRouter

from engine.agent.orchestrator import Orchestrator
from engine.agent.prompt import PromptBuilder
from engine.api.app import create_app
from engine.api.routes.oauth import OAuthRoutes
from engine.api.routes.webhooks import WebhookRoutes
from engine.auth.providers.registry import Providers
from engine.core.config import Config, PlatformSettings
from engine.core.protocols import JobQueue, TraceSink
from engine.core.types import ChannelRef, ChatMessage, ConfigError, SandboxError
from engine.data.cache import RedisProviderLimiter, RedisQueue, RedisRateLimiter
from engine.data.crypto import Vault
from engine.data.db import create_engine, sessions
from engine.data.repos.audit import PgAudit
from engine.data.repos.collaboration import PgCollaboration
from engine.data.repos.confirmations import PgConfirmations
from engine.data.repos.credentials import PgCredentials
from engine.data.repos.documents import PgDocuments
from engine.data.repos.org_context import PgOrgContext
from engine.data.repos.orgs import PgOrgs
from engine.data.repos.tool_config import PgToolConfig
from engine.data.repos.workspaces import PgWorkspaces
from engine.gateway.gateway import Gateway
from engine.llm.client import LiteLlmChat
from engine.llm.embeddings import LiteLlmEmbedder
from engine.llm.tracing import LangfuseTrace
from engine.memory.manager import MemoryManager
from engine.platforms.registry import Platforms
from engine.telemetry import logging as log_setup
from engine.telemetry import sentry
from engine.telemetry.metrics import Metrics
from engine.telemetry.progress import ProgressSink
from engine.telemetry.trace import Fanout, JsonlTrace
from engine.tools.executor import Executor
from engine.tools.registry import Registry
from engine.tools.sandbox.container import ContainerSandbox
from engine.tools.sandbox.schemas import SandboxSettings
from engine.workers.cleanup import cleanup, reap_sandboxes
from engine.workers.ingestion import Ingestion
from engine.workers.scheduler import Consumer, DailyAt, MonthlyFirst, Periodic, Scheduler
from engine.workers.spend import reset_monthly_spend
from engine.workers.token_refresh import refresh_expiring

log = log_setup.get("engine.wiring")

#: Where the system prompt templates live.
DELEGATED_TEMPLATE = "delegated.md.j2"

TEMPLATES = Path(__file__).resolve().parent / "agent" / "templates"

#: Release reported to Sentry.
RELEASE = "zipy@0.1.0"


class Conversations:
    """The conversation source, bound to the platforms once they are built.

    The platforms need the gateway, the gateway needs the orchestrator, and the orchestrator needs
    a conversation source that reads from the platforms. This holds that one edge open until the
    platforms exist. Reading before they are bound is a ConfigError.
    """

    def __init__(self) -> None:
        self._platforms: Platforms | None = None

    def bind(self, platforms: Platforms) -> None:
        """Point the source at the built platforms."""
        self._platforms = platforms

    async def recent(self, channel: ChannelRef, limit: int) -> list[ChatMessage]:
        """The recent messages of a conversation, from the platform it belongs to."""
        if self._platforms is None:
            raise ConfigError("the conversation source was read before the platforms were built")
        return await self._platforms.recent(channel, limit)


@dataclass(frozen=True)
class Assembled:
    """Everything serve runs, built from one configuration."""

    platforms: Platforms
    providers: Providers
    queue: JobQueue
    ingestion: Ingestion
    scheduler: Scheduler
    consumer: Consumer
    oauth: OAuthRoutes
    webhooks: WebhookRoutes
    metrics: Metrics | None


def system_template(name: str) -> str:
    """The system prompt template agent.system_template names. A missing file is a ConfigError."""
    path = TEMPLATES / name
    if not path.is_file():
        raise ConfigError(f"agent.system_template {name} is not a file in {TEMPLATES}")
    return path.read_text(encoding="utf-8")


def provider_scopes(config: Config) -> dict[str, list[str]]:
    """The scopes each provider is asked for: the union of its enabled tools' scopes."""
    scopes: dict[str, list[str]] = {name: [] for name in config.providers}
    for table in config.tools.values():
        if not table.enabled or not table.provider:
            continue
        wanted = scopes.setdefault(table.provider, [])
        wanted.extend(scope for scope in table.scopes if scope not in wanted)
    return scopes


def trace_sink(config: Config) -> TraceSink:
    """Every trace destination the configuration turns on, as one sink."""
    sinks: list[TraceSink] = []
    if config.telemetry.trace_dir:
        sinks.append(JsonlTrace(Path(config.telemetry.trace_dir)))
    langfuse = LangfuseTrace(config.telemetry)
    if langfuse.enabled:
        sinks.append(langfuse)
    # Last, so a watcher sees a line only once the event is recorded.
    sinks.append(ProgressSink())
    return Fanout(sinks)


def selected(config: Config, only: Sequence[str]) -> dict[str, PlatformSettings]:
    """The platform tables to build: those named by only, enabled or not, else the enabled ones."""
    if not only:
        return dict(config.platforms)
    unknown = sorted(set(only) - set(config.platforms))
    if unknown:
        raise ConfigError(f"no platform table for {', '.join(unknown)}")
    return {
        name: table.model_copy(update={"enabled": name in only})
        for name, table in config.platforms.items()
    }


def routers(platforms: Platforms) -> dict[str, APIRouter]:
    """The HTTP router of every running platform that serves one."""
    mounted = {}
    for name, platform in platforms.enabled.items():
        router = platform.router()
        if router is not None:
            mounted[name] = router
    return mounted


def assemble(config: Config, only: Sequence[str] = (), sandbox_ready: bool = True) -> Assembled:
    """Every dependency, composed from configuration. Builds nothing that talks to the network.

    sandbox_ready is what probe_sandbox found. False leaves the tool unoffered and attached files
    unread rather than failing at the first call.
    """
    if not sandbox_ready:
        config = config.model_copy(
            update={
                "tools": {
                    **config.tools,
                    "sandbox": config.tools["sandbox"].model_copy(update={"enabled": False}),
                },
                # files stays on: an attachment then says why it was not read, rather than
                # being dropped without a word.
            }
        )
    engine = create_engine(config.data)
    factory = sessions(engine)
    vault = Vault(config.data.fernet_key)

    orgs = PgOrgs(factory)
    workspaces = PgWorkspaces(factory, vault)
    org_context = PgOrgContext(factory)
    collaboration = PgCollaboration(factory)
    documents = PgDocuments(factory)
    credentials = PgCredentials(factory, vault)
    tool_config = PgToolConfig(factory)
    audit = PgAudit(factory)
    confirmations = PgConfirmations(factory)
    queue = RedisQueue(config.data)

    trace = trace_sink(config)
    metrics = Metrics() if config.telemetry.metrics else None
    embedder = LiteLlmEmbedder(config.models["embedding"])
    registry = Registry(config.tools)
    providers = Providers(config.providers, config.api.public_url)

    conversations = Conversations()
    provider_limiter = RedisProviderLimiter(config.data, config.rate_limit)
    settings = SandboxSettings.model_validate(registry.settings_for("sandbox").model_dump())
    sandbox = ContainerSandbox(settings) if sandbox_ready else None
    memory = MemoryManager(
        memory=config.memory,
        conversation=conversations,
        org_context=org_context,
        embedder=embedder,
        documents=documents,
        collaboration=collaboration,
        settings=config.collaboration,
        conditioning=config.models["chat"].conditioning,
        model=config.models["chat"].model,
        files=config.files,
        sandbox=sandbox,
    )
    orchestrator = Orchestrator(
        agent=config.agent,
        model=LiteLlmChat(config.models["chat"], trace),
        memory=memory,
        prompts=PromptBuilder(
            system_template(config.agent.system_template),
            config.app.name,
            system_template(DELEGATED_TEMPLATE),
        ),
        registry=registry,
        executor=Executor(
            registry,
            config.permissions,
            credentials,
            tool_config,
            audit,
            trace,
            provider_limiter,
            config.rate_limit,
        ),
        orgs=orgs,
        credentials=credentials,
        tool_config=tool_config,
        confirmations=confirmations,
        trace=trace,
        sandbox=sandbox,
    )
    gateway = Gateway(
        config=config,
        orchestrator=orchestrator,
        registry=registry,
        orgs=orgs,
        workspaces=workspaces,
        org_context=org_context,
        credentials=credentials,
        tool_config=tool_config,
        rate_limiter=RedisRateLimiter(config.data, config.rate_limit),
        collaboration=collaboration,
        metrics=metrics,
    )
    platforms = Platforms(selected(config, only), gateway, workspaces)
    conversations.bind(platforms)

    ingestion = Ingestion(
        registry, config.memory, credentials, embedder, documents, provider_limiter
    )
    workers = config.workers
    periodic = [
        Periodic(
            name="token_refresh",
            interval=timedelta(minutes=workers.token_refresh_minutes),
            run=lambda: refresh_expiring(workers, credentials, providers, platforms),
        ),
        Periodic(
            name="cleanup",
            interval=timedelta(minutes=15),
            run=DailyAt(
                workers.cleanup_hour_utc,
                lambda: cleanup(config.memory, confirmations, documents),
            ).tick,
        ),
        Periodic(
            name="spend_reset",
            interval=timedelta(hours=1),
            run=MonthlyFirst(lambda: reset_monthly_spend(orgs)).tick,
        ),
    ]
    if sandbox is not None:
        reaper = sandbox
        periodic.append(
            Periodic(
                name="sandbox_reap",
                interval=timedelta(minutes=5),
                run=lambda: reap_sandboxes(reaper),
            )
        )
    scheduler = Scheduler(periodic)
    return Assembled(
        platforms=platforms,
        providers=providers,
        queue=queue,
        ingestion=ingestion,
        scheduler=scheduler,
        consumer=Consumer(queue, ingestion.run, metrics=metrics),
        oauth=OAuthRoutes(
            providers=providers,
            credentials=credentials,
            notifier=platforms,
            state_key=config.data.fernet_key,
            scopes=provider_scopes(config),
        ),
        webhooks=WebhookRoutes(providers, queue),
        metrics=metrics,
    )


async def probe_sandbox(config: Config) -> bool:
    """Whether the container runtime answers.

    A runtime that does not answer is a ConfigError when the sandbox is required, and otherwise
    one line in the log: the sandbox tool goes unoffered and attached files go unread, and the
    rest of Zipy runs.
    """
    table = config.tools["sandbox"]
    if not table.enabled:
        return False
    settings = SandboxSettings.model_validate(table.options)
    try:
        await ContainerSandbox(settings).probe()
    except SandboxError as exc:
        if settings.required:
            raise ConfigError(
                f"tools.sandbox is required and {settings.runtime} did not answer: {exc}"
            ) from exc
        log.warning(
            "sandbox unavailable",
            runtime=settings.runtime,
            why=str(exc),
            effect="no sandbox tool, and attached files are not read",
            fix="start the runtime and run just sandbox-image, or set tools.sandbox.enabled false",
        )
        return False
    return True


async def serve(config: Config, only: Sequence[str] = ()) -> None:
    """Build stores, models, registries, agent, gateway, platforms, API and workers; run them.

    only runs just the named platforms, enabled or not, and skips the HTTP server when none of
    them needs it: zipy chat is serve with only local.
    """
    log_setup.configure(config.app)
    sentry.configure(config.telemetry, config.app.env, RELEASE)
    parts = assemble(config, only, sandbox_ready=await probe_sandbox(config))
    mounted = routers(parts.platforms)
    log.info(
        "starting",
        platforms=sorted(parts.platforms.enabled),
        tools=parts.platforms is not None and len(config.tools),
        http=bool(mounted) or not only,
    )
    async with asyncio.TaskGroup() as group:
        for name, platform in parts.platforms.enabled.items():
            group.create_task(platform.run(), name=f"platform:{name}")
        group.create_task(parts.scheduler.run(), name="scheduler")
        group.create_task(parts.consumer.run(), name="consumer")
        if mounted or not only:
            group.create_task(_http(config, parts, mounted), name="http")


async def _http(config: Config, parts: Assembled, mounted: dict[str, APIRouter]) -> None:
    """Serve the HTTP surface on the configured address."""
    app = create_app(parts.oauth, parts.webhooks, mounted, parts.metrics)
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=config.api.host,
            port=config.api.port,
            log_config=None,
            access_log=False,
        )
    )
    await server.serve()
