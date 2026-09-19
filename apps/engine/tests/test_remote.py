"""The MCP seam: catalogs, the params models they become, and one call over the wire."""

import json
from datetime import UTC, datetime

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from engine.core.config import load
from engine.core.types import (
    ChannelRef,
    ConfigError,
    CredentialError,
    MemberRef,
    OrgId,
    OrgToolConfig,
    ProviderAuth,
    RequestContext,
    Role,
    ToolError,
    WorkspaceRef,
)
from engine.tools.base import function_schema
from engine.tools.calendar.tool import CalendarTool
from engine.tools.drive.tool import DriveTool
from engine.tools.gmail.tool import GmailTool
from engine.tools.registry import Registry
from engine.tools.remote import (
    PROTOCOL_VERSION,
    Catalog,
    RemoteSettings,
    RemoteTool,
    actions_from,
    load_catalog,
    params_model,
    suggested_type,
)
from engine.tools.workspace.tool import WorkspaceTool

TOKEN = "ya29.a-google-access-token"
ENDPOINT = "https://calendarmcp.googleapis.com/mcp/v1"

#: Every tool whose actions come from a server rather than from Python.
REMOTE = (CalendarTool, DriveTool, GmailTool, WorkspaceTool)

#: What a server answers an initialize with when it speaks this client's revision.
HANDSHAKE = {"result": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}}}}


class Server:
    """A stand-in MCP server that records what it was asked and answers from a script."""

    def __init__(self, answers=None, stream=False, status=200, body=None):
        self.requests = []
        self.bodies = []
        self._answers = {"initialize": HANDSHAKE, **(answers or {})}
        self._stream = stream
        self._status = status
        self._body = body

    def handle(self, request):
        body = json.loads(request.content)
        self.requests.append(request)
        self.bodies.append(body)
        if self._status != 200:
            return httpx.Response(self._status, json={"error": "no"})
        if self._body is not None:
            return httpx.Response(200, text=self._body)
        if "id" not in body:
            return httpx.Response(202)
        answer = {"jsonrpc": "2.0", "id": body["id"], **self._answers.get(body["method"], {})}
        answer.setdefault("result", {})
        if not self._stream:
            return httpx.Response(200, json=answer)
        return httpx.Response(
            200,
            text=f"event: message\ndata: {json.dumps(answer)}\n\n",
            headers={"content-type": "text/event-stream"},
        )


def context():
    return RequestContext(
        org_id=OrgId("org-1"),
        channel=ChannelRef(WorkspaceRef("discord", "g1"), "c1"),
        member=MemberRef("discord", "u1"),
        role=Role.OFFICER,
        display_name="Ash",
        request_id="req-1",
        received_at=datetime(2026, 9, 19, tzinfo=UTC),
    )


def auth(provider="google"):
    return ProviderAuth(
        org_id=OrgId("org-1"),
        provider=provider,
        access_token=SecretStr(TOKEN),
        scopes=("https://www.googleapis.com/auth/calendar",),
        expires_at=None,
    )


def settings(**over):
    return RemoteSettings(endpoint=ENDPOINT, **over)


def calendar(server):
    return CalendarTool(settings(), transport=httpx.MockTransport(server.handle))


def called(server):
    """The tools/call body the server received."""
    return next(body for body in server.bodies if body.get("method") == "tools/call")


def text_result(text, **extra):
    return {"result": {"content": [{"type": "text", "text": text}], **extra}}


# ---------------------------------------------------------------- catalogs


def test_every_remote_tool_exposes_exactly_the_actions_zipy_toml_gives_a_type():
    tables = load().tools
    for cls in REMOTE:
        assert sorted(cls.catalog.exposed) == sorted(tables[cls.name].actions), cls.name


def test_every_remote_tool_points_at_the_endpoint_its_catalog_was_taken_from():
    tables = load().tools
    for cls in REMOTE:
        assert tables[cls.name].options["endpoint"] == cls.catalog.endpoint, cls.name


def test_a_tool_the_server_offers_but_the_catalog_does_not_expose_is_not_an_action():
    offered = set(CalendarTool.catalog.by_name())
    assert offered
    assert set(CalendarTool.actions) <= offered


def test_exposing_a_tool_the_server_does_not_offer_fails_to_load(tmp_path):
    (tmp_path / "catalog.json").write_text(
        json.dumps(
            {
                "endpoint": ENDPOINT,
                "fetched_at": "2026-09-19T00:00:00Z",
                "exposed": ["list_events", "invent_event"],
                "tools": [{"name": "list_events", "inputSchema": {"properties": {}}}],
            }
        )
    )
    with pytest.raises(ConfigError, match="invent_event"):
        load_catalog(str(tmp_path / "tool.py"))


def test_a_missing_catalog_is_a_config_error(tmp_path):
    with pytest.raises(ConfigError, match="readable MCP catalog"):
        load_catalog(str(tmp_path / "tool.py"))


def test_the_annotations_suggest_a_type_without_deciding_it():
    assert suggested_type({"annotations": {"readOnlyHint": True}}) == "read"
    assert suggested_type({"annotations": {"destructiveHint": True}}) == "destructive"
    assert suggested_type({"annotations": {}}) == "create"
    assert suggested_type({}) == "create"


def test_the_suggestion_is_not_what_zipy_toml_pins_for_update_event():
    entry = CalendarTool.catalog.by_name()["update_event"]
    assert suggested_type(entry) == "create"
    assert load().tools["calendar"].actions["update_event"].value == "destructive"


# ---------------------------------------------------------------- schemas


def test_a_required_field_is_required_and_the_rest_are_optional():
    model = params_model(
        "calendar",
        "list_events",
        {
            "properties": {"calendarId": {"type": "string"}, "maxResults": {"type": "integer"}},
            "required": ["calendarId"],
        },
    )
    assert model(calendarId="primary").maxResults is None
    with pytest.raises(ValidationError):
        model(maxResults=3)


def test_an_argument_the_server_never_named_is_refused():
    with pytest.raises(ValidationError):
        CalendarTool.actions["list_events"].params(calendarId="primary", nonsense=1)


def test_an_array_keeps_its_item_type_and_an_object_stays_a_mapping():
    model = params_model(
        "gmail",
        "search",
        {
            "properties": {
                "labels": {"type": "array", "items": {"type": "string"}},
                "filter": {"type": "object"},
            }
        },
    )
    assert model(labels=["a", "b"], filter={"k": 1}).labels == ["a", "b"]
    with pytest.raises(ValidationError):
        model(labels=[{"not": "a string"}])


def test_a_schema_construct_with_no_python_type_is_passed_through():
    model = params_model("gmail", "draft", {"properties": {"body": {"$ref": "#/$defs/Body"}}})
    assert model(body={"anything": True}).body == {"anything": True}


def test_the_model_is_shown_the_servers_own_schema_not_a_rebuilt_one():
    action = CalendarTool.actions["create_event"]
    schema = function_schema("calendar", "create_event", action)["function"]["parameters"]
    assert schema == CalendarTool.catalog.by_name()["create_event"]["inputSchema"]
    assert "$defs" in schema


def test_a_tool_without_an_input_schema_is_a_config_error():
    catalog = Catalog(
        endpoint=ENDPOINT,
        fetched_at="2026-09-19T00:00:00Z",
        exposed=["odd"],
        tools=[{"name": "odd", "inputSchema": {"properties": []}}],
    )
    with pytest.raises(ConfigError, match="inputSchema"):
        actions_from(catalog, "odd")


# ---------------------------------------------------------------- one call


@pytest.mark.anyio
async def test_a_call_initializes_then_runs_the_tool_with_the_orgs_token():
    server = Server({"tools/call": text_result("2 events")})
    params = CalendarTool.actions["list_events"].params(calendarId="primary")
    result = await calendar(server).execute(context(), "list_events", params, auth())
    assert result.text == "2 events"
    assert [body["method"] for body in server.bodies] == [
        "initialize",
        "notifications/initialized",
        "tools/call",
    ]
    assert called(server)["params"] == {
        "name": "list_events",
        "arguments": {"calendarId": "primary"},
    }
    assert server.requests[0].headers["authorization"] == f"Bearer {TOKEN}"


@pytest.mark.anyio
async def test_a_field_the_model_left_out_is_not_sent_as_null():
    server = Server({"tools/call": text_result("ok")})
    params = CalendarTool.actions["list_events"].params(calendarId="primary")
    await calendar(server).execute(context(), "list_events", params, auth())
    assert called(server)["params"]["arguments"] == {"calendarId": "primary"}


@pytest.mark.anyio
async def test_an_event_stream_answer_is_read_like_a_json_one():
    server = Server({"tools/call": text_result("streamed")}, stream=True)
    params = CalendarTool.actions["list_calendars"].params()
    result = await calendar(server).execute(context(), "list_calendars", params, auth())
    assert result.text == "streamed"


@pytest.mark.anyio
async def test_structured_content_comes_back_beside_the_text():
    server = Server({"tools/call": text_result("one", structuredContent={"count": 1})})
    params = CalendarTool.actions["list_calendars"].params()
    result = await calendar(server).execute(context(), "list_calendars", params, auth())
    assert result.structured == {"count": 1}


@pytest.mark.anyio
async def test_a_long_result_is_cut_and_says_so():
    server = Server({"tools/call": text_result("x" * 50)})
    tool = CalendarTool(settings(max_result_chars=10), transport=httpx.MockTransport(server.handle))
    result = await tool.execute(
        context(), "list_calendars", CalendarTool.actions["list_calendars"].params(), auth()
    )
    assert result.text == "x" * 10
    assert result.truncated


@pytest.mark.anyio
async def test_a_tool_that_reports_a_failure_is_a_tool_error():
    server = Server(
        {"tools/call": {"result": {"isError": True, "content": [{"text": "no such calendar"}]}}}
    )
    params = CalendarTool.actions["list_calendars"].params()
    with pytest.raises(ToolError, match="no such calendar"):
        await calendar(server).execute(context(), "list_calendars", params, auth())


@pytest.mark.anyio
async def test_a_jsonrpc_error_is_a_tool_error():
    server = Server({"tools/call": {"error": {"code": -32602, "message": "bad argument"}}})
    params = CalendarTool.actions["list_calendars"].params()
    with pytest.raises(ToolError, match="bad argument"):
        await calendar(server).execute(context(), "list_calendars", params, auth())


@pytest.mark.anyio
async def test_a_rejected_token_tells_the_org_to_reconnect():
    for status in (401, 403):
        server = Server(status=status)
        params = CalendarTool.actions["list_calendars"].params()
        with pytest.raises(CredentialError, match="reconnect google") as caught:
            await calendar(server).execute(context(), "list_calendars", params, auth())
        assert str(status) in str(caught.value)
        assert TOKEN not in str(caught.value)


@pytest.mark.anyio
async def test_an_http_failure_names_the_status_and_never_the_token():
    server = Server(status=503)
    params = CalendarTool.actions["list_calendars"].params()
    with pytest.raises(ToolError) as caught:
        await calendar(server).execute(context(), "list_calendars", params, auth())
    assert "503" in str(caught.value)
    assert TOKEN not in str(caught.value)


@pytest.mark.anyio
async def test_an_unreachable_server_is_a_tool_error():
    def refuse(request):
        raise httpx.ConnectError("refused")

    tool = CalendarTool(settings(), transport=httpx.MockTransport(refuse))
    params = CalendarTool.actions["list_calendars"].params()
    with pytest.raises(ToolError, match="could not be reached"):
        await tool.execute(context(), "list_calendars", params, auth())


@pytest.mark.anyio
async def test_a_tool_of_another_provider_is_a_credential_error():
    server = Server({"tools/call": text_result("ok")})
    params = CalendarTool.actions["list_calendars"].params()
    with pytest.raises(CredentialError, match="google is not connected"):
        await calendar(server).execute(context(), "list_calendars", params, auth(provider="notion"))


@pytest.mark.anyio
async def test_a_session_id_the_server_sets_is_sent_back():
    class Stateful(Server):
        def handle(self, request):
            response = super().handle(request)
            response.headers["Mcp-Session-Id"] = "sess-9"
            return response

    server = Stateful({"tools/call": text_result("ok")})
    params = CalendarTool.actions["list_calendars"].params()
    await calendar(server).execute(context(), "list_calendars", params, auth())
    assert server.requests[-1].headers["mcp-session-id"] == "sess-9"


# ---------------------------------------------------------------- audit and policy


def test_the_target_of_an_action_is_the_first_thing_the_server_requires():
    tool = CalendarTool(settings())
    params = CalendarTool.actions["delete_event"].params(eventId="evt-1", calendarId="primary")
    assert tool.target("delete_event", params) == "evt-1"


def test_an_action_that_requires_nothing_has_no_target():
    tool = CalendarTool(settings())
    assert tool.target("list_calendars", CalendarTool.actions["list_calendars"].params()) == ""


def test_the_registry_accepts_every_remote_tool():
    registry = Registry(load().tools)
    for cls in REMOTE:
        assert cls.name in registry.names
        assert issubclass(registry.tool_class(cls.name), RemoteTool)


def test_gmail_exposes_nothing_that_sends_trashes_or_marks_spam():
    forbidden = {"trash", "spam", "send"}
    for action in GmailTool.actions:
        assert not any(word in action for word in forbidden), action


def test_drive_exposes_nothing_that_writes_while_its_scope_is_read_only():
    table = load().tools["drive"]
    assert table.scopes == ["https://www.googleapis.com/auth/drive.readonly"]
    assert all(kind.value == "read" for kind in table.actions.values())


# ---------------------------------------------------------------- what an org may not change


def test_an_org_cannot_move_a_tools_endpoint():
    registry = Registry(load().tools)
    override = OrgToolConfig("calendar", enabled=True, overrides={"endpoint": "https://elsewhere"})
    with pytest.raises(ConfigError, match="not overridable per org"):
        registry.settings_for("calendar", override)


def test_every_remote_tool_locks_its_endpoint():
    for cls in REMOTE:
        assert "endpoint" in cls.locked, cls.name


def test_an_endpoint_that_is_not_https_is_refused():
    for bad in ("http://mcp.example/v1", "ftp://mcp.example", "mcp.example"):
        with pytest.raises(ValidationError, match="https"):
            RemoteSettings(endpoint=bad)


def test_a_limit_that_would_silence_every_result_is_refused_at_load():
    for bad in ({"max_result_chars": 0}, {"max_result_chars": -1}, {"timeout_secs": 0}):
        with pytest.raises(ValidationError):
            settings(**bad)


# ---------------------------------------------------------------- what a server may not do


@pytest.mark.anyio
async def test_a_body_that_is_not_json_is_a_tool_error():
    server = Server(body="<html>a proxy sign-in page</html>")
    params = CalendarTool.actions["list_calendars"].params()
    with pytest.raises(ToolError, match="not JSON"):
        await calendar(server).execute(context(), "list_calendars", params, auth())


@pytest.mark.anyio
async def test_a_server_speaking_another_revision_is_refused_before_the_call():
    server = Server({"initialize": {"result": {"protocolVersion": "1999-01-01"}}})
    params = CalendarTool.actions["list_calendars"].params()
    with pytest.raises(ToolError, match="1999-01-01"):
        await calendar(server).execute(context(), "list_calendars", params, auth())
    assert [body["method"] for body in server.bodies] == ["initialize"]


@pytest.mark.anyio
async def test_structured_content_over_the_limit_is_dropped_rather_than_passed_on():
    big = {"rows": ["x" * 100 for _ in range(50)]}
    server = Server({"tools/call": text_result("ok", structuredContent=big)})
    tool = CalendarTool(settings(max_result_chars=50), transport=httpx.MockTransport(server.handle))
    result = await tool.execute(
        context(), "list_calendars", CalendarTool.actions["list_calendars"].params(), auth()
    )
    assert result.structured is None
    assert result.truncated


@pytest.mark.anyio
async def test_a_failure_the_server_reports_is_cut_to_the_same_limit():
    server = Server({"tools/call": {"result": {"isError": True, "content": [{"text": "y" * 200}]}}})
    tool = CalendarTool(settings(max_result_chars=20), transport=httpx.MockTransport(server.handle))
    with pytest.raises(ToolError) as caught:
        await tool.execute(
            context(), "list_calendars", CalendarTool.actions["list_calendars"].params(), auth()
        )
    assert "y" * 20 in str(caught.value)
    assert "y" * 21 not in str(caught.value)
