"""The workspace tool, run on the Google Workspace MCP server."""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

from pydantic import BaseModel

from engine.tools.base import Action
from engine.tools.remote import Catalog, RemoteSettings, RemoteTool, actions_from, load_catalog

CATALOG = load_catalog(__file__)


class WorkspaceTool(RemoteTool[RemoteSettings]):
    """One search across Drive, Gmail, Calendar and Chat, for a question naming no product."""

    name: ClassVar[str] = "workspace"
    provider: ClassVar[str] = "google"
    owns: ClassVar[tuple[str, ...]] = ()
    settings_model: ClassVar[type[BaseModel]] = RemoteSettings
    catalog: ClassVar[Catalog] = CATALOG
    actions: ClassVar[Mapping[str, Action]] = actions_from(CATALOG, "workspace")
