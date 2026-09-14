"""Params, results and settings of the calendar tool."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CalendarSettings(_Model):
    """[tools.calendar] settings an org may override."""

    default_event_minutes: int = 60
    default_reminder_minutes: int = 10


class Event(_Model):
    """One calendar event."""

    id: str
    title: str
    start: datetime
    end: datetime
    location: str = ""
    attendees: list[str] = []
    link: str = ""


class ListEventsParams(_Model):
    """Events between two times, optionally matching a query."""

    time_min: datetime
    time_max: datetime
    query: str = ""


class EventList(_Model):
    """Events in start order."""

    events: list[Event]


class FindFreeSlotsParams(_Model):
    """Free time within a window."""

    start: datetime
    end: datetime
    min_minutes: int = 30


class Slot(_Model):
    """One free interval."""

    start: datetime
    end: datetime


class FreeSlots(_Model):
    """Free intervals in start order."""

    slots: list[Slot]


class CreateEventParams(_Model):
    """A new event. end defaults to start plus default_event_minutes."""

    title: str
    start: datetime
    end: datetime | None = None
    location: str = ""
    description: str = ""
    attendees: list[EmailStr] = []


class UpdateEventParams(_Model):
    """Changes to one event. Unset fields stay as they are."""

    event_id: str
    title: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    location: str | None = None
    attendees: list[EmailStr] | None = None


class DeleteEventParams(_Model):
    """One event to delete."""

    event_id: str


class Done(_Model):
    """An action that returns nothing but success."""

    ok: bool = True
