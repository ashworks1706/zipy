"""The calendar tool: its schemas, the requests it builds, and what it makes of the answers."""

from datetime import UTC, datetime

import pytest
from googleapiclient.errors import HttpError
from pydantic import SecretStr, ValidationError

from engine.core.types import CredentialError, OrgId, ProviderAuth, ToolError
from engine.tools.calendar import client as client_module
from engine.tools.calendar.schemas import (
    CalendarSettings,
    CreateEventParams,
    DeleteEventParams,
    FindFreeSlotsParams,
    ListEventsParams,
    UpdateEventParams,
)
from engine.tools.calendar.tool import CalendarTool

TOKEN = "ya29.a-google-access-token"


class FakeRequest:
    """One prepared Google request that records itself when executed."""

    def __init__(self, calls, name, kwargs, result, error):
        self._calls = calls
        self._name = name
        self._kwargs = kwargs
        self._result = result
        self._error = error

    def execute(self):
        self._calls.append((self._name, self._kwargs))
        if self._error is not None:
            raise self._error
        return self._result


class FakeCollection:
    """One Google API collection, such as events or freebusy."""

    def __init__(self, calls, prefix, results, error):
        self._calls = calls
        self._prefix = prefix
        self._results = results
        self._error = error

    def __getattr__(self, method):
        def prepare(**kwargs):
            name = f"{self._prefix}.{method}"
            return FakeRequest(self._calls, name, kwargs, self._results.get(name, {}), self._error)

        return prepare


class FakeService:
    """A stand-in for the discovery-built Google service."""

    def __init__(self, results=None, error=None):
        self.calls = []
        self._results = results or {}
        self._error = error

    def events(self):
        return FakeCollection(self.calls, "events", self._results, self._error)

    def freebusy(self):
        return FakeCollection(self.calls, "freebusy", self._results, self._error)


def google(monkeypatch, results=None, error=None):
    """Put a fake Google service behind the client and return it."""
    service = FakeService(results, error)
    monkeypatch.setattr(client_module, "build", lambda *args, **kwargs: service)
    return service


def auth(provider="google"):
    return ProviderAuth(
        org_id=OrgId("org-1"),
        provider=provider,
        access_token=SecretStr(TOKEN),
        scopes=("https://www.googleapis.com/auth/calendar",),
        expires_at=None,
    )


def tool():
    return CalendarTool(CalendarSettings())


def http_error(status, message):
    class Response:
        def __init__(self):
            self.status = status
            self.reason = message

    body = f'{{"error": {{"code": {status}, "message": "{message}"}}}}'.encode()
    return HttpError(Response(), body, uri="https://www.googleapis.com/calendar/v3/events")


EVENT = {
    "id": "evt-1",
    "summary": "Exec Board",
    "start": {"dateTime": "2026-09-25T15:00:00-07:00"},
    "end": {"dateTime": "2026-09-25T16:00:00-07:00"},
    "location": "CPCOM 210",
    "attendees": [{"email": "sarah@asu.edu"}, {"displayName": "no email"}],
    "htmlLink": "https://calendar.google.com/event?eid=evt-1",
}


def test_a_workshop_with_two_attendees_parses():
    params = CreateEventParams.model_validate(
        {
            "title": "Intro to LLMs workshop",
            "start": "2026-09-22T18:00:00-07:00",
            "location": "CPCOM 210",
            "attendees": ["me@asu.edu", "sarah@asu.edu"],
        }
    )
    assert params.end is None
    assert params.start == datetime.fromisoformat("2026-09-22T18:00:00-07:00")


def test_an_attendee_that_is_not_an_email_is_rejected():
    with pytest.raises(ValidationError):
        CreateEventParams.model_validate(
            {"title": "x", "start": "2026-09-22T18:00:00", "attendees": ["sarah"]}
        )


def test_every_action_has_a_json_schema():
    for action in CalendarTool.actions.values():
        assert action.params.model_json_schema()["type"] == "object"


async def test_list_events_asks_the_primary_calendar_for_the_window(monkeypatch):
    service = google(monkeypatch, {"events.list": {"items": [EVENT]}})
    params = ListEventsParams(
        time_min=datetime(2026, 9, 25, tzinfo=UTC), time_max=datetime(2026, 9, 26, tzinfo=UTC)
    )

    result = await tool().execute("list_events", params, auth())

    name, sent = service.calls[0]
    assert name == "events.list"
    assert sent["calendarId"] == "primary"
    assert sent["timeMin"] == "2026-09-25T00:00:00Z"
    assert sent["timeMax"] == "2026-09-26T00:00:00Z"
    assert sent["singleEvents"] is True
    assert sent["orderBy"] == "startTime"
    assert sent["q"] is None
    event = result.events[0]
    assert event.id == "evt-1"
    assert event.title == "Exec Board"
    assert event.start == datetime(2026, 9, 25, 22, tzinfo=UTC)
    assert event.attendees == ["sarah@asu.edu"]
    assert event.link.endswith("evt-1")


async def test_list_events_passes_a_query_through(monkeypatch):
    service = google(monkeypatch, {"events.list": {"items": []}})
    params = ListEventsParams(
        time_min=datetime(2026, 9, 25, tzinfo=UTC),
        time_max=datetime(2026, 9, 26, tzinfo=UTC),
        query="exec board",
    )

    await tool().execute("list_events", params, auth())

    assert service.calls[0][1]["q"] == "exec board"


async def test_list_events_rejects_a_window_that_ends_before_it_starts(monkeypatch):
    google(monkeypatch)
    params = ListEventsParams(
        time_min=datetime(2026, 9, 26, tzinfo=UTC), time_max=datetime(2026, 9, 25, tzinfo=UTC)
    )

    with pytest.raises(ToolError, match="time_max after time_min"):
        await tool().execute("list_events", params, auth())


async def test_find_free_slots_returns_the_gaps_between_busy_periods(monkeypatch):
    busy = {
        "calendars": {
            "primary": {
                "busy": [
                    {"start": "2026-09-25T10:00:00Z", "end": "2026-09-25T11:00:00Z"},
                    {"start": "2026-09-25T11:30:00Z", "end": "2026-09-25T12:00:00Z"},
                ]
            }
        }
    }
    service = google(monkeypatch, {"freebusy.query": busy})
    params = FindFreeSlotsParams(
        start=datetime(2026, 9, 25, 9, tzinfo=UTC),
        end=datetime(2026, 9, 25, 13, tzinfo=UTC),
        min_minutes=30,
    )

    result = await tool().execute("find_free_slots", params, auth())

    assert service.calls[0][1]["body"]["items"] == [{"id": "primary"}]
    assert [(s.start.hour, s.start.minute) for s in result.slots] == [(9, 0), (11, 0), (12, 0)]
    assert result.slots[-1].end == datetime(2026, 9, 25, 13, tzinfo=UTC)


async def test_find_free_slots_drops_gaps_shorter_than_the_minimum(monkeypatch):
    busy = {
        "calendars": {
            "primary": {
                "busy": [
                    {"start": "2026-09-25T09:10:00Z", "end": "2026-09-25T10:00:00Z"},
                    {"start": "2026-09-25T10:15:00Z", "end": "2026-09-25T13:00:00Z"},
                ]
            }
        }
    }
    google(monkeypatch, {"freebusy.query": busy})
    params = FindFreeSlotsParams(
        start=datetime(2026, 9, 25, 9, tzinfo=UTC),
        end=datetime(2026, 9, 25, 13, tzinfo=UTC),
        min_minutes=30,
    )

    result = await tool().execute("find_free_slots", params, auth())

    assert result.slots == []


async def test_create_event_ends_it_after_the_configured_length(monkeypatch):
    service = google(monkeypatch, {"events.insert": EVENT})
    params = CreateEventParams(
        title="Intro to LLMs workshop",
        start=datetime(2026, 9, 22, 18, tzinfo=UTC),
        location="CPCOM 210",
        attendees=["sarah@asu.edu"],
    )

    result = await tool().execute("create_event", params, auth())

    name, sent = service.calls[0]
    assert name == "events.insert"
    body = sent["body"]
    assert body["summary"] == "Intro to LLMs workshop"
    assert body["start"] == {"dateTime": "2026-09-22T18:00:00Z"}
    assert body["end"] == {"dateTime": "2026-09-22T19:00:00Z"}
    assert body["attendees"] == [{"email": "sarah@asu.edu"}]
    assert body["reminders"]["overrides"] == [{"method": "popup", "minutes": 10}]
    assert "description" not in body
    assert result.id == "evt-1"


async def test_create_event_honours_an_orgs_overridden_length(monkeypatch):
    service = google(monkeypatch, {"events.insert": EVENT})
    params = CreateEventParams(title="Tabling", start=datetime(2026, 9, 22, 18, tzinfo=UTC))

    await CalendarTool(CalendarSettings(default_event_minutes=90)).execute(
        "create_event", params, auth()
    )

    assert service.calls[0][1]["body"]["end"] == {"dateTime": "2026-09-22T19:30:00Z"}


async def test_create_event_rejects_an_end_before_its_start(monkeypatch):
    google(monkeypatch)
    params = CreateEventParams(
        title="Tabling",
        start=datetime(2026, 9, 22, 18, tzinfo=UTC),
        end=datetime(2026, 9, 22, 17, tzinfo=UTC),
    )

    with pytest.raises(ToolError, match="end after start"):
        await tool().execute("create_event", params, auth())


async def test_update_event_patches_only_the_fields_given(monkeypatch):
    service = google(monkeypatch, {"events.patch": EVENT})
    params = UpdateEventParams(event_id="evt-1", start=datetime(2026, 9, 25, 23, tzinfo=UTC))

    await tool().execute("update_event", params, auth())

    name, sent = service.calls[0]
    assert name == "events.patch"
    assert sent["eventId"] == "evt-1"
    assert sent["body"] == {"start": {"dateTime": "2026-09-25T23:00:00Z"}}


async def test_update_event_without_a_change_says_so(monkeypatch):
    google(monkeypatch)

    with pytest.raises(ToolError, match="at least one field"):
        await tool().execute("update_event", UpdateEventParams(event_id="evt-1"), auth())


async def test_delete_event_deletes_and_reports_success(monkeypatch):
    service = google(monkeypatch, {"events.delete": ""})

    result = await tool().execute("delete_event", DeleteEventParams(event_id="evt-1"), auth())

    assert service.calls[0][0] == "events.delete"
    assert service.calls[0][1]["eventId"] == "evt-1"
    assert result.ok is True


async def test_a_google_refusal_becomes_a_tool_error_naming_the_reason(monkeypatch):
    google(monkeypatch, error=http_error(403, "Insufficient Permission"))

    with pytest.raises(ToolError) as caught:
        await tool().execute("delete_event", DeleteEventParams(event_id="evt-1"), auth())

    assert "403" in str(caught.value)
    assert "Insufficient Permission" in str(caught.value)


async def test_an_expired_token_becomes_a_credential_error(monkeypatch):
    google(monkeypatch, error=http_error(401, "Invalid Credentials"))
    params = ListEventsParams(
        time_min=datetime(2026, 9, 25, tzinfo=UTC), time_max=datetime(2026, 9, 26, tzinfo=UTC)
    )

    with pytest.raises(CredentialError, match="expired or revoked"):
        await tool().execute("list_events", params, auth())


async def test_a_tool_without_the_orgs_google_account_refuses_to_run():
    params = ListEventsParams(
        time_min=datetime(2026, 9, 25, tzinfo=UTC), time_max=datetime(2026, 9, 26, tzinfo=UTC)
    )

    with pytest.raises(CredentialError, match="google is not connected"):
        await tool().execute("list_events", params, None)

    with pytest.raises(CredentialError, match="google is not connected"):
        await tool().execute("list_events", params, auth(provider="notion"))


async def test_the_token_reaches_neither_a_result_nor_an_error(monkeypatch):
    google(monkeypatch, {"events.list": {"items": [EVENT]}})
    params = ListEventsParams(
        time_min=datetime(2026, 9, 25, tzinfo=UTC), time_max=datetime(2026, 9, 26, tzinfo=UTC)
    )

    result = await tool().execute("list_events", params, auth())
    assert TOKEN not in result.model_dump_json()

    google(monkeypatch, error=http_error(401, "Invalid Credentials"))
    with pytest.raises(CredentialError) as caught:
        await tool().execute("list_events", params, auth())
    assert TOKEN not in str(caught.value)
