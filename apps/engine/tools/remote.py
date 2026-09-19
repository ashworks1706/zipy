"""Tools whose actions run on a remote MCP server rather than a client written here.

A remote tool declares no actions in Python. It ships a catalog: the server's own tools/list
response, fetched by zipy mcp refresh and committed, plus the list of tools this deployment
exposes. Actions are built from the exposed entries at import, so the tools the model is offered
change with a file rather than with code, and a tool the catalog gains is refused until someone
lists it and gives it an action type in zipy.toml.

The server describes what a tool takes; zipy.toml decides what the tool is allowed to be. Action
types, permissions, confirmation, rate limits and the audit log are unchanged and stay here.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, ClassVar

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, create_model

from engine.core.types import ConfigError, CredentialError, ProviderAuth, ToolError
from engine.tools.base import Action, BaseTool, require_auth

#: The MCP revision this client speaks.
PROTOCOL_VERSION = "2025-06-18"

#: The file each remote tool ships beside its tool.py.
CATALOG_NAME = "catalog.json"

#: JSON Schema types that become a Python type. Anything else is passed through unvalidated.
SCALARS: Mapping[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
}


class RemoteSettings(BaseModel):
    """[tools.name] settings every MCP-backed tool takes."""

    model_config = ConfigDict(extra="forbid")

    endpoint: str
    timeout_secs: float = 30.0
    max_result_chars: int = 4000


class RemoteResult(BaseModel):
    """What a remote tool returned: its text blocks, and its structured content when it sent any."""

    model_config = ConfigDict(extra="forbid")

    text: str
    structured: dict[str, Any] | None = None
    truncated: bool = False


class Catalog(BaseModel):
    """A server's tools/list response, and the tools this deployment exposes from it."""

    model_config = ConfigDict(extra="forbid")

    endpoint: str
    fetched_at: str
    exposed: list[str]
    tools: list[dict[str, Any]]

    def by_name(self) -> dict[str, dict[str, Any]]:
        """Every tool the server offers, by name."""
        return {str(tool["name"]): tool for tool in self.tools}


def load_catalog(package_file: str) -> Catalog:
    """The catalog beside a tool's module. A missing or malformed file is a ConfigError."""
    path = Path(package_file).with_name(CATALOG_NAME)
    try:
        catalog = Catalog.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"{path} is not a readable MCP catalog: {exc}") from exc
    missing = sorted(set(catalog.exposed) - set(catalog.by_name()))
    if missing:
        raise ConfigError(f"{path} exposes tools the server does not offer: {missing}")
    return catalog


def _annotated(schema: Mapping[str, Any], required: bool) -> tuple[Any, Any]:
    """One property as a pydantic field. An unsupported schema is accepted unvalidated."""
    kind = schema.get("type")
    if kind == "array":
        item = schema.get("items", {})
        inner = SCALARS.get(str(item.get("type")), Any) if isinstance(item, dict) else Any
        annotation: Any = list[inner]  # type: ignore[valid-type]
    elif kind == "object":
        annotation = dict[str, Any]
    else:
        annotation = SCALARS.get(str(kind), Any)
    description = str(schema.get("description", ""))
    if required:
        return annotation, Field(description=description)
    return annotation | None, Field(default=None, description=description)


def params_model(tool: str, action: str, schema: Mapping[str, Any]) -> type[BaseModel]:
    """A model that validates what the server said this tool takes."""
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        raise ConfigError(f"{tool}.{action} has no usable inputSchema properties")
    required = set(schema.get("required", []))
    fields = {
        name: _annotated(prop, name in required)
        for name, prop in properties.items()
        if isinstance(prop, dict)
    }
    model: type[BaseModel] = create_model(
        f"{tool.title()}{action.title().replace('_', '')}Params",
        __config__=ConfigDict(extra="forbid"),
        **fields,  # type: ignore[call-overload]
    )
    return model


def actions_from(catalog: Catalog, tool: str) -> dict[str, Action]:
    """The actions a catalog's exposed tools become. The server's own schema reaches the model."""
    offered = catalog.by_name()
    built = {}
    for name in catalog.exposed:
        entry = offered[name]
        schema = entry.get("inputSchema", {})
        built[name] = Action(
            description=str(entry.get("description", "")).strip(),
            params=params_model(tool, name, schema),
            result=RemoteResult,
            parameters=dict(schema),
        )
    return built


async def list_tools(
    endpoint: str, timeout_secs: float = 30.0, transport: httpx.AsyncBaseTransport | None = None
) -> list[dict[str, Any]]:
    """Every tool a server offers. Needs no credential: tools/list describes, it does not act."""
    settings = RemoteSettings(endpoint=endpoint, timeout_secs=timeout_secs)
    session = Session(settings, SecretStr(""), transport)
    async with httpx.AsyncClient(timeout=timeout_secs, transport=transport) as client:
        result = await session.request(client, "tools/list", {})
    tools = result.get("tools", [])
    return [tool for tool in tools if isinstance(tool, dict)]


def suggested_type(entry: Mapping[str, Any]) -> str:
    """The action type a server's annotations suggest. Pinning it in zipy.toml stays manual."""
    hints = entry.get("annotations", {})
    hints = hints if isinstance(hints, dict) else {}
    if hints.get("destructiveHint"):
        return "destructive"
    return "read" if hints.get("readOnlyHint") else "create"


def _payload(response: httpx.Response) -> dict[str, Any]:
    """One JSON-RPC response, whether the server answered as JSON or as an event stream."""
    if "text/event-stream" not in response.headers.get("content-type", ""):
        parsed = response.json()
        return parsed if isinstance(parsed, dict) else {}
    for line in response.text.splitlines():
        if line.startswith("data:"):
            parsed = json.loads(line[len("data:") :].strip())
            if isinstance(parsed, dict) and ("result" in parsed or "error" in parsed):
                return parsed
    raise ToolError("the MCP server sent an event stream with no response in it")


def _text_of(result: Mapping[str, Any]) -> str:
    """The text blocks of a tools/call result, joined."""
    blocks = result.get("content", [])
    blocks = blocks if isinstance(blocks, list) else []
    return "\n".join(
        str(block.get("text", "")) for block in blocks if isinstance(block, dict)
    ).strip()


class Session:
    """One MCP conversation over streamable HTTP. Opened per tool call, closed with it."""

    def __init__(
        self,
        settings: RemoteSettings,
        token: SecretStr,
        transport: httpx.AsyncBaseTransport | None = None,
        provider: str = "the account",
    ) -> None:
        self._settings = settings
        self._token = token
        self._transport = transport
        self._provider = provider
        self._session_id = ""
        self._next_id = 0

    async def call(self, tool: str, arguments: Mapping[str, Any]) -> RemoteResult:
        """Run one remote tool. A transport, protocol or tool failure is a ToolError."""
        async with httpx.AsyncClient(
            timeout=self._settings.timeout_secs, transport=self._transport
        ) as client:
            await self.request(client, "initialize", self._handshake())
            await self._notify(client, "notifications/initialized")
            result = await self.request(
                client, "tools/call", {"name": tool, "arguments": dict(arguments)}
            )
        if result.get("isError"):
            raise ToolError(f"{tool} failed: {_text_of(result) or 'the server gave no reason'}")
        return self._trimmed(result)

    def _trimmed(self, result: Mapping[str, Any]) -> RemoteResult:
        """The result the model reads, cut to max_result_chars."""
        text = _text_of(result)
        limit = self._settings.max_result_chars
        structured = result.get("structuredContent")
        return RemoteResult(
            text=text[:limit],
            structured=structured if isinstance(structured, dict) else None,
            truncated=len(text) > limit,
        )

    def _handshake(self) -> dict[str, Any]:
        """What this client tells the server it is."""
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "zipy", "version": "0.1.0"},
        }

    def _headers(self) -> dict[str, str]:
        token = self._token.get_secret_value()
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    async def _post(self, client: httpx.AsyncClient, body: dict[str, Any]) -> httpx.Response:
        try:
            response = await client.post(
                self._settings.endpoint, headers=self._headers(), json=body
            )
        except httpx.HTTPError as exc:
            raise ToolError(f"the MCP server could not be reached: {type(exc).__name__}") from exc
        if response.status_code in (401, 403):
            raise CredentialError(
                f"the {self._provider} credential is expired, revoked or missing a scope "
                f"(HTTP {response.status_code}); reconnect {self._provider}"
            )
        if response.is_error:
            raise ToolError(f"the MCP server answered HTTP {response.status_code}")
        return response

    async def request(
        self, client: httpx.AsyncClient, method: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """One JSON-RPC request. A JSON-RPC error becomes a ToolError."""
        self._next_id += 1
        response = await self._post(
            client,
            {"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params},
        )
        self._session_id = response.headers.get("Mcp-Session-Id", self._session_id)
        payload = _payload(response)
        if "error" in payload:
            error = payload["error"] if isinstance(payload["error"], dict) else {}
            raise ToolError(f"{method} was refused: {error.get('message', 'no reason given')}")
        result = payload.get("result", {})
        return result if isinstance(result, dict) else {}

    async def _notify(self, client: httpx.AsyncClient, method: str) -> None:
        """One JSON-RPC notification. Servers that ignore it answer with no body."""
        await self._post(client, {"jsonrpc": "2.0", "method": method, "params": {}})


class RemoteTool[S: RemoteSettings](BaseTool[S]):
    """A tool backed by an MCP server. Its actions come from catalog.json, not from here."""

    catalog: ClassVar[Catalog]
    settings_model: ClassVar[type[BaseModel]] = RemoteSettings

    def __init__(self, settings: S, transport: httpx.AsyncBaseTransport | None = None) -> None:
        super().__init__(settings)
        self._transport = transport

    def target(self, action: str, params: BaseModel) -> str:
        """The first required field of the action, which is what the server acts on."""
        schema = self.actions[action].parameters or {}
        for name in schema.get("required", []):
            value = getattr(params, str(name), None)
            if isinstance(value, str | int) and value != "":
                return str(value)
        return ""

    async def execute(self, action: str, params: BaseModel, auth: ProviderAuth | None) -> BaseModel:
        """Run the action on the server, with the org's token as the bearer."""
        credential = require_auth(auth, self.provider)
        session = Session(self.settings, credential.access_token, self._transport, self.provider)
        return await session.call(action, params.model_dump(exclude_none=True))
