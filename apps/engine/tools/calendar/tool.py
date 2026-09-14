"""The calendar tool."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, ClassVar

from pydantic import BaseModel

from engine.core.types import ProviderAuth
from engine.tools.base import Action, BaseTool, require_auth
from engine.tools.calendar import schemas as s
from engine.tools.calendar.client import CalendarClient


class CalendarTool(BaseTool[s.CalendarSettings]):
    """Google Calendar for the org's shared calendar."""

    name: ClassVar[str] = "calendar"
    provider: ClassVar[str] = "google"
    owns: ClassVar[tuple[str, ...]] = ("googleapiclient",)
    settings_model: ClassVar[type[BaseModel]] = s.CalendarSettings
    actions: ClassVar[Mapping[str, Action]] = {
        "list_events": Action("List events between two times.", s.ListEventsParams, s.EventList),
        "find_free_slots": Action(
            "Find free time in a window.", s.FindFreeSlotsParams, s.FreeSlots
        ),
        "create_event": Action("Create an event.", s.CreateEventParams, s.Event),
        "update_event": Action("Change an existing event.", s.UpdateEventParams, s.Event),
        "delete_event": Action("Delete an event.", s.DeleteEventParams, s.Done),
    }

    async def execute(self, action: str, params: BaseModel, auth: ProviderAuth | None) -> BaseModel:
        client = CalendarClient(require_auth(auth, self.provider), self.settings)
        handlers: dict[str, Callable[[Any], Awaitable[BaseModel]]] = {
            "list_events": client.list_events,
            "find_free_slots": client.find_free_slots,
            "create_event": client.create_event,
            "update_event": client.update_event,
            "delete_event": client.delete_event,
        }
        return await handlers[action](params)
