"""The Google Calendar API."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from engine.core.types import CredentialError, ProviderAuth, ToolError, ZipyError
from engine.tools.calendar.schemas import (
    CalendarSettings,
    CreateEventParams,
    DeleteEventParams,
    Done,
    Event,
    EventList,
    FindFreeSlotsParams,
    FreeSlots,
    ListEventsParams,
    Slot,
    UpdateEventParams,
)

CALENDAR_ID = "primary"
MAX_EVENTS = 250

# The OAuth credential google-api-python-client sends, built from the access token alone.
_bearer: Callable[..., Any] = Credentials


def _service(auth: ProviderAuth) -> Any:
    """A Calendar v3 service bound to the org's credential."""
    credentials = _bearer(token=auth.access_token.get_secret_value())
    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


def _failed(action: str, exc: HttpError) -> ZipyError:
    """The error the model reads. Carries the status and Google's reason, never the token."""
    status = int(getattr(exc.resp, "status", 0) or 0)
    reason = str(getattr(exc, "reason", "") or "").strip() or "the request was rejected"
    if status == 401:
        return CredentialError(f"the Google credential is expired or revoked: {reason}")
    return ToolError(f"Google Calendar refused {action} with status {status}: {reason}")


async def _run(action: str, call: Callable[[], Any]) -> Any:
    """Run one blocking Google request off the event loop."""
    try:
        return await asyncio.to_thread(call)
    except HttpError as exc:
        raise _failed(action, exc) from exc


def _utc(value: datetime) -> datetime:
    """The time as an aware UTC time. A naive time is read as UTC."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _stamp(value: datetime) -> str:
    """An RFC3339 time Google accepts."""
    return _utc(value).isoformat().replace("+00:00", "Z")


def _edge(edge: dict[str, Any], action: str) -> datetime:
    """The time of one end of an event, timed or all-day."""
    raw = str(edge.get("dateTime") or edge.get("date") or "")
    if not raw:
        raise ToolError(f"Google Calendar returned an event without a time for {action}")
    return _utc(datetime.fromisoformat(raw))


def _event(raw: dict[str, Any], action: str) -> Event:
    """One event as the model sees it."""
    attendees = [str(a["email"]) for a in raw.get("attendees", []) if a.get("email")]
    return Event(
        id=str(raw.get("id", "")),
        title=str(raw.get("summary", "")),
        start=_edge(raw.get("start", {}), action),
        end=_edge(raw.get("end", {}), action),
        location=str(raw.get("location", "")),
        attendees=attendees,
        link=str(raw.get("htmlLink", "")),
    )


class CalendarClient:
    """Calls the org's primary calendar with its Google credential."""

    def __init__(self, auth: ProviderAuth, settings: CalendarSettings) -> None:
        self._auth = auth
        self._settings = settings

    async def list_events(self, params: ListEventsParams) -> EventList:
        """Events in the window, in start order."""
        if params.time_max <= params.time_min:
            raise ToolError("list_events needs time_max after time_min")
        request = (
            _service(self._auth)
            .events()
            .list(
                calendarId=CALENDAR_ID,
                timeMin=_stamp(params.time_min),
                timeMax=_stamp(params.time_max),
                q=params.query or None,
                singleEvents=True,
                orderBy="startTime",
                maxResults=MAX_EVENTS,
            )
        )
        raw = await _run("list_events", request.execute)
        return EventList(events=[_event(item, "list_events") for item in raw.get("items", [])])

    async def find_free_slots(self, params: FindFreeSlotsParams) -> FreeSlots:
        """Intervals in the window with no event, via the freebusy endpoint."""
        if params.end <= params.start:
            raise ToolError("find_free_slots needs end after start")
        if params.min_minutes <= 0:
            raise ToolError("find_free_slots needs min_minutes above zero")
        body = {
            "timeMin": _stamp(params.start),
            "timeMax": _stamp(params.end),
            "items": [{"id": CALENDAR_ID}],
        }
        request = _service(self._auth).freebusy().query(body=body)
        raw = await _run("find_free_slots", request.execute)
        busy = raw.get("calendars", {}).get(CALENDAR_ID, {}).get("busy", [])
        return FreeSlots(slots=self._gaps(params, busy))

    def _gaps(self, params: FindFreeSlotsParams, busy: list[dict[str, Any]]) -> list[Slot]:
        """The window minus every busy period, keeping intervals of min_minutes or more."""
        window_start, window_end = _utc(params.start), _utc(params.end)
        least = timedelta(minutes=params.min_minutes)
        periods = sorted(
            (
                _utc(datetime.fromisoformat(str(p["start"]))),
                _utc(datetime.fromisoformat(str(p["end"]))),
            )
            for p in busy
            if p.get("start") and p.get("end")
        )
        slots: list[Slot] = []
        cursor = window_start
        for start, end in periods:
            if start > cursor and start - cursor >= least:
                slots.append(Slot(start=cursor, end=min(start, window_end)))
            cursor = max(cursor, end)
            if cursor >= window_end:
                break
        if window_end - cursor >= least:
            slots.append(Slot(start=cursor, end=window_end))
        return [slot for slot in slots if slot.end - slot.start >= least]

    async def create_event(self, params: CreateEventParams) -> Event:
        """The created event, with its link."""
        minutes = self._settings.default_event_minutes
        end = params.end or params.start + timedelta(minutes=minutes)
        if end <= params.start:
            raise ToolError("create_event needs end after start")
        body: dict[str, Any] = {
            "summary": params.title,
            "start": {"dateTime": _stamp(params.start)},
            "end": {"dateTime": _stamp(end)},
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "popup", "minutes": self._settings.default_reminder_minutes}
                ],
            },
        }
        if params.location:
            body["location"] = params.location
        if params.description:
            body["description"] = params.description
        if params.attendees:
            body["attendees"] = [{"email": str(a)} for a in params.attendees]
        request = (
            _service(self._auth)
            .events()
            .insert(calendarId=CALENDAR_ID, body=body, sendUpdates="all")
        )
        return _event(await _run("create_event", request.execute), "create_event")

    async def update_event(self, params: UpdateEventParams) -> Event:
        """The event after the patch."""
        body: dict[str, Any] = {}
        if params.title is not None:
            body["summary"] = params.title
        if params.start is not None:
            body["start"] = {"dateTime": _stamp(params.start)}
        if params.end is not None:
            body["end"] = {"dateTime": _stamp(params.end)}
        if params.location is not None:
            body["location"] = params.location
        if params.attendees is not None:
            body["attendees"] = [{"email": str(a)} for a in params.attendees]
        if not body:
            raise ToolError("update_event needs at least one field to change")
        request = (
            _service(self._auth)
            .events()
            .patch(calendarId=CALENDAR_ID, eventId=params.event_id, body=body, sendUpdates="all")
        )
        return _event(await _run("update_event", request.execute), "update_event")

    async def delete_event(self, params: DeleteEventParams) -> Done:
        """Delete one event."""
        request = (
            _service(self._auth)
            .events()
            .delete(calendarId=CALENDAR_ID, eventId=params.event_id, sendUpdates="all")
        )
        await _run("delete_event", request.execute)
        return Done()
