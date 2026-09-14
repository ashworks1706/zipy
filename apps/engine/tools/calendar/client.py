"""The Google Calendar API."""

from __future__ import annotations

from engine.core.types import ProviderAuth
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
    UpdateEventParams,
)


class CalendarClient:
    """Calls the org's primary calendar with its Google credential."""

    def __init__(self, auth: ProviderAuth, settings: CalendarSettings) -> None:
        self._auth = auth
        self._settings = settings

    async def list_events(self, params: ListEventsParams) -> EventList:
        """Events in the window, in start order."""
        raise NotImplementedError

    async def find_free_slots(self, params: FindFreeSlotsParams) -> FreeSlots:
        """Intervals in the window with no event, via the freebusy endpoint."""
        raise NotImplementedError

    async def create_event(self, params: CreateEventParams) -> Event:
        """The created event, with its link."""
        raise NotImplementedError

    async def update_event(self, params: UpdateEventParams) -> Event:
        """The event after the patch."""
        raise NotImplementedError

    async def delete_event(self, params: DeleteEventParams) -> Done:
        """Delete one event."""
        raise NotImplementedError
