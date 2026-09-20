"""The Gateway: one entry point per inbound event, returning what to post."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime
from uuid import uuid4

from engine.agent.orchestrator import Orchestrator
from engine.auth.state import ConnectState, sign
from engine.cognition.conditioning import render as render_collaborator
from engine.core.config import Budget, Config
from engine.core.protocols import (
    CollaborationStore,
    CredentialStore,
    OrgContextStore,
    OrgStore,
    RateLimiter,
    ToolConfigStore,
    WorkspaceStore,
)
from engine.core.types import (
    STATED_WEIGHT,
    AgentResult,
    Attachment,
    ChannelRef,
    ConfigError,
    Dimension,
    Evidence,
    FactCategory,
    MemberRef,
    NeedsConfirmation,
    Org,
    OrgFact,
    OrgToolConfig,
    Progress,
    Provenance,
    RequestContext,
    Role,
    Signal,
    StoreError,
    Workspace,
    WorkspaceRef,
    ZipyError,
)
from engine.gateway.admin import AdminCommand, Verb, parse
from engine.gateway.messages import (
    Answer,
    Capabilities,
    ConfirmPrompt,
    Inbound,
    InboundAnswer,
    Outbound,
    Text,
    WorkspaceInstalled,
)
from engine.gateway.render import split
from engine.telemetry.logging import bind, get
from engine.telemetry.metrics import Metrics
from engine.tools.registry import Registry

log = get("engine.gateway")

UNLINKED = (
    "This workspace is not linked to a Zipy org yet, so there is nothing for me to answer from.\n"
    "An admin can add Zipy to the workspace again: installing it creates the org, links this "
    "workspace to it, and makes the installer an admin.\n"
    "Once it is linked, run setup here to connect the org's accounts."
)

WELCOME = (
    "Zipy is here. This workspace is now linked to a new org, and whoever added me is its admin.\n"
    "Run setup to connect the org's accounts, and status at any time to see what is connected."
)

NO_DIRECT_MESSAGES = (
    "This platform has no direct messages, so this answer is posted in the channel. "
    "Anyone who can read it can use the links in it."
)

FACT_FORMAT = (
    "Give the fact as remember <key>: <value>, for example "
    "remember budget sheet: the Finance folder in Drive. A category may come first, one of "
    f"{', '.join(c.value for c in FactCategory)}."
)

#: The verbs that read, or write only the caller's own row. Everything else changes the org.
OWN = (Verb.STATUS, Verb.PREFER)

ADMIN_ONLY = tuple(verb for verb in Verb if verb not in OWN)

#: How prefer names each end of each dimension.
DIRECTIONS = {"more": 1.0, "less": 0.0}

PREFER_FORMAT = (
    "Say prefer more <dimension> or prefer less <dimension>, for example prefer less depth, "
    f"where dimension is one of {', '.join(d.value for d in Dimension)}. "
    "prefer on its own shows what I have read about you, and prefer forget drops it."
)

PREFER_OFF = "Collaboration state is off in this deployment, so there is nothing to set."


def _coerce(words: tuple[str, ...]) -> object:
    """A config value as the boolean, integer, float or string it reads as."""
    raw = " ".join(words)
    if raw.lower() in ("true", "false"):
        return raw.lower() == "true"
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw


def _plural(count: int, noun: str) -> str:
    """A count and its noun, with the s the count asks for."""
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _preference(args: tuple[str, ...]) -> tuple[float, Dimension]:
    """The target and dimension a prefer command names. Anything else is a ConfigError."""
    if len(args) != 2:
        raise ConfigError(f"that is not a preference I can set. {PREFER_FORMAT}")
    direction, dimension = args[0].lower(), args[1].lower()
    if direction not in DIRECTIONS or dimension not in tuple(Dimension):
        raise ConfigError(f"that is not a preference I can set. {PREFER_FORMAT}")
    return DIRECTIONS[direction], Dimension(dimension)


def _fact(args: tuple[str, ...]) -> OrgFact:
    """The fact a remember command carries. Anything else is a ConfigError."""
    words = list(args)
    category = FactCategory.ORG_INFO
    if words and words[0].lower() in tuple(FactCategory):
        category = FactCategory(words.pop(0).lower())
    key, separator, value = " ".join(words).partition(":")
    if not separator or not key.strip() or not value.strip():
        raise ConfigError(f"that fact has no key and value. {FACT_FORMAT}")
    return OrgFact(category=category, key=key.strip(), value=value.strip())


class Gateway:
    """Handles inbound events from every platform. Holds no per-request state."""

    def __init__(
        self,
        config: Config,
        orchestrator: Orchestrator,
        registry: Registry,
        orgs: OrgStore,
        workspaces: WorkspaceStore,
        org_context: OrgContextStore,
        credentials: CredentialStore,
        tool_config: ToolConfigStore,
        rate_limiter: RateLimiter,
        collaboration: CollaborationStore,
        metrics: Metrics | None = None,
    ) -> None:
        self._config = config
        self._orchestrator = orchestrator
        self._registry = registry
        self._orgs = orgs
        self._workspaces = workspaces
        self._org_context = org_context
        self._credentials = credentials
        self._tool_config = tool_config
        self._rate_limiter = rate_limiter
        self._collaboration = collaboration
        self._metrics = metrics

    async def message(
        self,
        event: Inbound,
        capabilities: Capabilities,
        watcher: Callable[[Progress], None] | None = None,
    ) -> list[Outbound]:
        """Resolve org and role, rate limit, then an admin command or the agent.

        A workspace with no org gets setup instructions. A confirmation becomes a ConfirmPrompt;
        text is split to the platform's message limit.
        """
        started = time.perf_counter()
        workspace = await self._workspaces.get(event.channel.workspace)
        if workspace is None:
            return self._counted(
                event.channel, started, "unlinked", [Text(event.channel, UNLINKED)]
            )
        ctx = await self._context(
            workspace,
            event.channel,
            event.member,
            event.display_name,
            event.received_at,
            event.reply_to,
            watcher,
            Attachment.accepted(event.images, self._config.agent.max_images),
            Attachment.readable(event.images, self._config.files.max_per_message),
        )
        logger = bind(ctx)
        if not await self._rate_limiter.allow(ctx.org_id, ctx.member):
            logger.info("message refused", reason="rate_limited")
            replies = self._limited(ctx, capabilities)
            return self._counted(ctx.channel, started, "rate_limited", replies)
        command = parse(event.text)
        if command is not None:
            logger.info("admin command", verb=command.verb.value)
            replies = await self._admin(ctx, command, capabilities)
            return self._counted(ctx.channel, started, "admin", replies)
        try:
            result = await self._orchestrator.handle(ctx, event.text, capabilities.markup)
        except ZipyError as exc:
            logger.warning("request failed", error=type(exc).__name__)
            replies = self._failed(ctx, exc, capabilities)
            return self._counted(ctx.channel, started, "error", replies)
        outcome = "confirmation" if isinstance(result, NeedsConfirmation) else "reply"
        logger.info("request answered", outcome=outcome)
        replies = self._rendered(ctx, result, capabilities)
        return self._counted(ctx.channel, started, outcome, replies)

    async def answer(self, event: InboundAnswer, capabilities: Capabilities) -> list[Outbound]:
        """Confirm or cancel a pending call, if the member may answer it."""
        workspace = await self._workspaces.get(event.channel.workspace)
        if workspace is None:
            return [Text(event.channel, UNLINKED)]
        ctx = await self._context(workspace, event.channel, event.member, "", event.received_at)
        logger = bind(ctx)
        if not await self._rate_limiter.allow(ctx.org_id, ctx.member):
            return self._limited(ctx, capabilities)
        try:
            if event.answer is Answer.CANCEL:
                await self._orchestrator.cancel(ctx, event.confirmation_id)
                logger.info("confirmation answered", answer=event.answer.value)
                return self._texts(ctx.channel, "Cancelled. Nothing was changed.", capabilities)
            result = await self._orchestrator.confirm(
                ctx, event.confirmation_id, capabilities.markup
            )
        except ZipyError as exc:
            logger.warning("confirmation failed", error=type(exc).__name__)
            return self._failed(ctx, exc, capabilities)
        logger.info("confirmation answered", answer=event.answer.value)
        return self._rendered(ctx, result, capabilities)

    async def linked(self, workspace: WorkspaceRef) -> bool:
        """Whether this workspace already belongs to an org."""
        return await self._workspaces.get(workspace) is not None

    async def installed(self, event: WorkspaceInstalled, budget: Budget) -> list[Outbound]:
        """Create an org for a new workspace, link it, make the installer an admin, welcome."""
        existing = await self._workspaces.get(event.channel.workspace)
        if existing is not None:
            return [
                Text(
                    event.channel,
                    f"This workspace is already linked to {existing.name}. "
                    "Run status to see what is connected.",
                )
            ]
        org = await self._orgs.create(event.name, budget.monthly_cents)
        await self._workspaces.link(
            Workspace(
                ref=event.channel.workspace,
                org_id=org.org_id,
                name=event.name,
                notice_channel=event.channel,
            )
        )
        await self._orgs.set_role(org.org_id, event.installed_by, Role.ADMIN)
        log.info("workspace linked", org_id=str(org.org_id), platform=event.channel.platform)
        return [Text(event.channel, WELCOME)]

    async def _context(
        self,
        workspace: Workspace,
        channel: ChannelRef,
        member: MemberRef,
        display_name: str,
        received_at: datetime,
        reply_to: str = "",
        watcher: Callable[[Progress], None] | None = None,
        images: tuple[Attachment, ...] = (),
        files: tuple[Attachment, ...] = (),
    ) -> RequestContext:
        """The context of one request: its org, its member's role, and a new request id."""
        return RequestContext(
            org_id=workspace.org_id,
            channel=channel,
            member=member,
            role=await self._orgs.role(workspace.org_id, member),
            display_name=display_name,
            request_id=uuid4().hex,
            received_at=received_at,
            reply_to=reply_to,
            watcher=watcher,
            images=images,
            files=files,
        )

    async def _admin(
        self, ctx: RequestContext, command: AdminCommand, capabilities: Capabilities
    ) -> list[Outbound]:
        """Run one admin command without the model. Every failure answers in words."""
        if command.verb in ADMIN_ONLY and ctx.role is not Role.ADMIN:
            return self._texts(
                ctx.channel, f"Only an admin may run {command.verb.value}.", capabilities
            )
        try:
            return await self._run_admin(ctx, command, capabilities)
        except ZipyError as exc:
            return self._failed(ctx, exc, capabilities)

    async def _run_admin(
        self, ctx: RequestContext, command: AdminCommand, capabilities: Capabilities
    ) -> list[Outbound]:
        """The body of one admin command."""
        args = command.args
        match command.verb:
            case Verb.SETUP:
                return self._private(ctx, self._setup_text(), capabilities)
            case Verb.CONNECT:
                return self._private(ctx, self._connect_text(ctx, args), capabilities)
            case Verb.ENABLE:
                return self._texts(ctx.channel, await self._toggle(ctx, args, True), capabilities)
            case Verb.DISABLE:
                return self._texts(ctx.channel, await self._toggle(ctx, args, False), capabilities)
            case Verb.CONFIG:
                return self._texts(ctx.channel, await self._configure(ctx, args), capabilities)
            case Verb.REMEMBER:
                fact = _fact(args)
                await self._org_context.remember(ctx.org_id, fact)
                return self._texts(
                    ctx.channel, f"Noted under {fact.category.value}: {fact.key}.", capabilities
                )
            case Verb.FORGET:
                return self._texts(ctx.channel, await self._forget(ctx, args), capabilities)
            case Verb.STATUS:
                return self._texts(ctx.channel, await self._status(ctx), capabilities)
            case Verb.PREFER:
                return self._texts(ctx.channel, await self._prefer(ctx, args), capabilities)

    def _setup_text(self) -> str:
        """The onboarding steps, naming the providers this Zipy has enabled."""
        providers = [name for name, table in self._config.providers.items() if table.enabled]
        if not providers:
            raise ConfigError("no [providers.*] table is enabled, so there is nothing to connect")
        steps = "\n".join(
            f"{number}. connect {name}" for number, name in enumerate(sorted(providers), start=1)
        )
        return (
            "Setting up this org:\n"
            f"{steps}\n"
            f"{len(providers) + 1}. remember <key>: <value> for what I should always know, such "
            "as where the budget sheet lives and when exec board meets\n"
            f"{len(providers) + 2}. status to see what is connected\n"
            "Each connect answers with a private link. Sign in with the org's shared account, "
            "not a personal one."
        )

    def _connect_text(self, ctx: RequestContext, args: tuple[str, ...]) -> str:
        """A private, signed link for one provider."""
        enabled = sorted(name for name, table in self._config.providers.items() if table.enabled)
        provider = args[0].lower() if args else ""
        if provider not in enabled:
            raise ConfigError(
                f"connect needs one of {', '.join(enabled)}, not {provider or 'a provider'}"
            )
        key = self._config.data.fernet_key
        if not key.get_secret_value():
            raise ConfigError("data.fernet_key is not set, so a connect link cannot be signed")
        state = sign(
            ConnectState(
                org_id=ctx.org_id,
                member=ctx.member,
                provider=provider,
                issued_at=ctx.received_at,
            ),
            key,
        )
        url = f"{self._config.api.public_url.rstrip('/')}/auth/{provider}?state={state}"
        return (
            f"Connect {provider} with this link. It is for you and it expires:\n{url}\n"
            "Sign in with the org's shared account."
        )

    async def _toggle(self, ctx: RequestContext, args: tuple[str, ...], enabled: bool) -> str:
        """Enable or disable one tool for this org, keeping its settings."""
        tool = self._tool_name(args, "enable" if enabled else "disable")
        overrides = await self._tool_config.overrides(ctx.org_id)
        current = overrides.get(tool)
        await self._tool_config.set(
            ctx.org_id,
            OrgToolConfig(
                tool=tool, enabled=enabled, overrides=dict(current.overrides) if current else {}
            ),
        )
        return f"{tool} is now {'enabled' if enabled else 'disabled'} for this org."

    async def _configure(self, ctx: RequestContext, args: tuple[str, ...]) -> str:
        """Set one per-org tool setting, validated against the tool's settings model."""
        tool = self._tool_name(args, "config")
        if len(args) < 3:
            raise ConfigError(f"config needs a tool, a key and a value, as config {tool} key value")
        overrides = await self._tool_config.overrides(ctx.org_id)
        current = overrides.get(tool)
        merged = dict(current.overrides) if current else {}
        key = args[1]
        merged[key] = _coerce(args[2:])
        candidate = OrgToolConfig(
            tool=tool, enabled=current.enabled if current else True, overrides=merged
        )
        self._registry.settings_for(tool, candidate)
        await self._tool_config.set(ctx.org_id, candidate)
        return f"{tool}.{key} is now {merged[key]!r} for this org."

    async def _forget(self, ctx: RequestContext, args: tuple[str, ...]) -> str:
        """Drop one org fact."""
        key = " ".join(args).strip()
        if not key:
            raise ConfigError("forget needs the key of a fact, as forget budget sheet")
        known = {fact.key for fact in await self._org_context.facts(ctx.org_id)}
        if key not in known:
            raise ConfigError(f"this org has no fact called {key}")
        await self._org_context.forget(ctx.org_id, key)
        return f"Forgotten: {key}."

    async def _status(self, ctx: RequestContext) -> str:
        """What is connected, which tools the org has, and what it has spent."""
        org = await self._org(ctx)
        connected = await self._credentials.connected(ctx.org_id)
        overrides = await self._tool_config.overrides(ctx.org_id)
        available = self._registry.available(connected, overrides)
        providers = sorted(name for name, table in self._config.providers.items() if table.enabled)
        missing = [name for name in providers if name not in connected]
        facts = await self._org_context.facts(ctx.org_id)
        lines = [
            org.name,
            f"Connected: {', '.join(sorted(connected)) or 'nothing yet'}",
            f"Not connected: {', '.join(missing) or 'nothing'}",
            f"Tools: {', '.join(available) or 'none available yet'}",
            f"Facts: {len(facts)}",
            f"Spend: {org.spent_cents} of {org.budget_cents} cents this month",
        ]
        if self._config.collaboration.enabled:
            lines.append(await self._preferences(ctx))
        return "\n".join(lines)

    async def _prefer(self, ctx: RequestContext, args: tuple[str, ...]) -> str:
        """Show, set or drop the caller's own collaboration state. Never another person's."""
        if not self._config.collaboration.enabled:
            return PREFER_OFF
        if not args:
            return await self._preferences(ctx)
        if len(args) == 1 and args[0].lower() == "forget":
            await self._collaboration.forget(ctx.org_id, ctx.member)
            return "Dropped what I had read about how you work."
        direction, dimension = _preference(args)
        await self._collaboration.observe(
            ctx.org_id,
            ctx.member,
            [
                Signal(
                    dimension=dimension,
                    target=direction,
                    evidence=Evidence.STATED_PREFERENCE,
                    weight=STATED_WEIGHT,
                )
            ],
            Provenance(
                request_id=ctx.request_id,
                arm=self._config.collaboration.arm,
                model=self._config.models["chat"].model,
            ),
        )
        return await self._preferences(ctx)

    async def _preferences(self, ctx: RequestContext) -> str:
        """What the caller's own state currently asks for, in the words the prompt gets."""
        state = await self._collaboration.state(ctx.org_id, ctx.member)
        lines = render_collaborator(state, self._config.collaboration.min_observations)
        read = _plural(state.observations, "observation")
        if not lines:
            return (
                f"I have {read} of how you work, which is not enough to change anything yet.\n"
                f"{PREFER_FORMAT}"
            )
        return f"How I work with you, from {read}:\n{lines}"

    def _tool_name(self, args: tuple[str, ...], verb: str) -> str:
        """The tool an admin command names. An unknown tool is a ConfigError."""
        name = args[0].lower() if args else ""
        if name not in self._registry.names:
            raise ConfigError(
                f"{verb} needs one of {', '.join(self._registry.names)}, not {name or 'a tool'}"
            )
        return name

    async def _org(self, ctx: RequestContext) -> Org:
        """The org of the request. An org that is not stored is a StoreError."""
        org = await self._orgs.get(ctx.org_id)
        if org is None:
            raise StoreError(f"org {ctx.org_id} is not stored")
        return org

    def _rendered(
        self, ctx: RequestContext, result: AgentResult, capabilities: Capabilities
    ) -> list[Outbound]:
        """What the agent returned, as messages this platform can post."""
        if isinstance(result, NeedsConfirmation):
            pending = result.pending
            prompt = ConfirmPrompt(
                channel=ctx.channel,
                confirmation_id=pending.id,
                summary=pending.summary,
                expires_at=pending.expires_at,
            )
            if capabilities.buttons:
                return [prompt]
            typed = f"Reply {Answer.CONFIRM.value} or {Answer.CANCEL.value}."
            return [prompt, Text(ctx.channel, typed)]
        return self._texts(ctx.channel, result.text, capabilities)

    def _failed(
        self, ctx: RequestContext, exc: ZipyError, capabilities: Capabilities
    ) -> list[Outbound]:
        """What a failed request says. The error names what is missing; nothing is guessed."""
        return self._texts(ctx.channel, str(exc), capabilities)

    def _limited(self, ctx: RequestContext, capabilities: Capabilities) -> list[Outbound]:
        """What a member over the rate limit is told, before any model call."""
        per_minute = self._config.rate_limit.per_member_per_minute
        return self._texts(
            ctx.channel,
            f"That is more than {per_minute} messages in a minute, so I am holding off. "
            "Ask me again shortly.",
            capabilities,
        )

    def _private(
        self, ctx: RequestContext, text: str, capabilities: Capabilities
    ) -> list[Outbound]:
        """An answer meant for one member, in a direct message where the platform has them."""
        if not capabilities.direct_messages:
            return self._texts(ctx.channel, f"{NO_DIRECT_MESSAGES}\n\n{text}", capabilities)
        return [
            Text(ctx.channel, piece, ctx.member)
            for piece in split(text, capabilities.message_limit)
        ]

    def _texts(self, channel: ChannelRef, text: str, capabilities: Capabilities) -> list[Outbound]:
        """One reply, split to the platform's message limit."""
        return [Text(channel, piece) for piece in split(text, capabilities.message_limit)]

    def _counted(
        self, channel: ChannelRef, started: float, outcome: str, replies: list[Outbound]
    ) -> list[Outbound]:
        """Count one message by platform and outcome, and how long it took. Never by org."""
        if self._metrics is not None:
            self._metrics.messages.labels(platform=channel.platform, outcome=outcome).inc()
            self._metrics.request_seconds.labels(platform=channel.platform).observe(
                time.perf_counter() - started
            )
        return replies
