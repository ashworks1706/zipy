"""The calendar tool's schemas."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from engine.tools.calendar.schemas import CreateEventParams
from engine.tools.calendar.tool import CalendarTool


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
