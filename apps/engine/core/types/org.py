"""Orgs, the workspaces linked to them, and what an org has told Zipy about itself."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from engine.core.types.identity import ChannelRef, OrgId, WorkspaceRef


@dataclass(frozen=True)
class Org:
    """One tenant: a student organization, on any number of workspaces."""

    org_id: OrgId
    name: str
    setup_complete: bool
    budget_cents: int
    spent_cents: float


@dataclass(frozen=True)
class Workspace:
    """A workspace linked to an org, and where Zipy posts notices for it."""

    ref: WorkspaceRef
    org_id: OrgId
    name: str
    notice_channel: ChannelRef | None


class FactCategory(StrEnum):
    """The section of the system prompt an org fact is shown under."""

    TOOL_MAPPING = "tool_mapping"
    ORG_INFO = "org_info"
    WORKFLOW = "workflow"
    PREFERENCE = "preference"


@dataclass(frozen=True)
class OrgFact:
    """One persistent fact, injected into every system prompt for its org."""

    category: FactCategory
    key: str
    value: str


@dataclass(frozen=True)
class OrgToolConfig:
    """An org's override of one tool: enabled or not, and settings merged over zipy.toml."""

    tool: str
    enabled: bool
    overrides: dict[str, object]
