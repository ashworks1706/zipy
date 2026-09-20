"""One gateway built for an eval run: the real loop and the real model, over fixtures.

Everything that would reach a network other than the model is a double, so a case is the same run
every time and the only variable is the model. The collaboration store is the one thing a case
writes to: the contrast sets a state and runs the case against it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from engine.agent.orchestrator import Orchestrator
from engine.agent.prompt import PromptBuilder
from engine.cognition.state import Cognition
from engine.core.config import Config
from engine.core.doubles import (
    AllowAll,
    MemoryAudit,
    MemoryCollaboration,
    MemoryConfirmations,
    MemoryConversation,
    MemoryCredentials,
    MemoryDocuments,
    MemoryOrgContext,
    MemoryOrgs,
    MemoryToolConfig,
    MemoryTrace,
    MemoryWorkspaces,
    NoLimit,
)
from engine.core.protocols import ChatModel
from engine.core.types import (
    ChannelRef,
    FactCategory,
    MemberRef,
    Org,
    OrgFact,
    OrgId,
    Role,
    Workspace,
    WorkspaceRef,
)
from engine.gateway.gateway import Gateway
from engine.gateway.messages import Capabilities
from engine.llm.client import LiteLlmChat
from engine.llm.embeddings import LiteLlmEmbedder
from engine.memory.manager import MemoryManager
from engine.tools.executor import Executor
from engine.tools.registry import Registry
from engine.wiring import system_template
from testbed.evals import fixtures

#: The surface a case is asked on. A plain one, so no case is scored on a platform's formatting.
SURFACE = Capabilities(
    markup="plain", message_limit=100_000, buttons=False, threads=True, direct_messages=True
)

WORKSPACE = WorkspaceRef("local", "evals")
CHANNEL = ChannelRef(WORKSPACE, "evals")
MEMBER = MemberRef("local", "officer")
ORG = OrgId("00000000-0000-0000-0000-00000000e7a1")

#: The budget of the eval org, high enough that no case is refused for spend.
BUDGET_CENTS = 1_000_000


@dataclass
class Stack:
    """A gateway and the doubles a run is read back from."""

    gateway: Gateway
    audit: MemoryAudit
    collaboration: MemoryCollaboration
    confirmations: MemoryConfirmations
    org_id: OrgId = ORG
    channel: ChannelRef = CHANNEL
    member: MemberRef = MEMBER
    received_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def _org_context(raw: dict[str, Any]) -> MemoryOrgContext:
    """The org facts the fixtures give every case, under org_info unless they name a category."""
    facts = {
        str(fact["key"]): OrgFact(
            category=FactCategory(fact.get("category", FactCategory.ORG_INFO.value)),
            key=str(fact["key"]),
            value=str(fact["value"]),
        )
        for fact in raw.get("org", {}).get("facts", [])
    }
    return MemoryOrgContext(by_org={ORG: facts})


def _enabled(config: Config) -> dict[str, Any]:
    """Every [tools.*] table with enabled true.

    A fixture stands in for the provider, so what one deployment happens to have turned on decides
    nothing here: a case is scored on the runtime, not on the org that ran it.
    """
    on = {"enabled": True}
    return {name: table.model_copy(update=on) for name, table in config.tools.items()}


def build(config: Config, raw: dict[str, Any], model: ChatModel | None = None) -> Stack:
    """A gateway over the fixtures, with the real tool loop.

    model stands in for the configured one, which is how the suite is tested without one.
    """
    tables = _enabled(config)
    registry = Registry(tables)
    answers = dict(raw.get("tools", {}))
    replayed = Registry(tables, fixtures.classes(registry, answers))

    orgs = MemoryOrgs()
    orgs.orgs[ORG] = Org(ORG, str(raw.get("org", {}).get("name", "Evals")), True, BUDGET_CENTS, 0)
    orgs.roles[(ORG, MEMBER)] = Role.OFFICER
    workspaces = MemoryWorkspaces()
    workspaces.links[WORKSPACE] = Workspace(WORKSPACE, ORG, "Evals", CHANNEL)
    credentials = MemoryCredentials()
    credentials.auths.update(fixtures.auths(ORG, replayed))
    org_context = _org_context(raw)
    tool_config = MemoryToolConfig()
    confirmations = MemoryConfirmations()
    collaboration = MemoryCollaboration()
    audit = MemoryAudit()
    trace = MemoryTrace()

    orchestrator = Orchestrator(
        agent=config.agent,
        model=model or LiteLlmChat(config.models["chat"], trace),
        memory=MemoryManager(
            memory=config.memory,
            conversation=MemoryConversation(),
            org_context=org_context,
            embedder=LiteLlmEmbedder(config.models["embedding"]),
            documents=MemoryDocuments(),
            cognition=Cognition(
                store=collaboration,
                settings=config.collaboration,
                model=config.models["chat"].model,
            ),
        ),
        prompts=PromptBuilder(system_template(config.agent.system_template), config.app.name),
        registry=replayed,
        executor=Executor(
            registry=replayed,
            permissions=config.permissions,
            credentials=credentials,
            tool_config=tool_config,
            audit=audit,
            trace=trace,
            limiter=NoLimit(),
            limits=config.rate_limit,
        ),
        orgs=orgs,
        credentials=credentials,
        tool_config=tool_config,
        confirmations=confirmations,
        trace=trace,
    )
    gateway = Gateway(
        config=config,
        orchestrator=orchestrator,
        registry=replayed,
        orgs=orgs,
        workspaces=workspaces,
        org_context=org_context,
        credentials=credentials,
        tool_config=tool_config,
        rate_limiter=AllowAll(),
        collaboration=collaboration,
    )
    return Stack(
        gateway=gateway,
        audit=audit,
        collaboration=collaboration,
        confirmations=confirmations,
    )
