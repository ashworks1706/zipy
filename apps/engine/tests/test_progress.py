"""Live progress: the line each trace event renders as, and the card that collects them."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import discord
import pytest

from engine.core.types import (
    ChannelRef,
    Progress,
    ProgressStyle,
    WorkspaceRef,
    ZipyError,
    progress,
)
from engine.gateway.messages import Outbound, Text
from engine.platforms.cards import ANSWERING, BULLET, THINKING, Card
from engine.platforms.discord.turn import Turn

STYLE = ProgressStyle()


def line(name: str, **data: object) -> Progress | None:
    return progress(name, dict(data), STYLE)


# ---------------------------------------------------------------- the lines


def test_a_started_tool_and_its_result_share_a_slot_so_one_writes_over_the_other():
    started = line(
        "tool_started", id="c1", action="calendar.create_event", arguments={"day": "fri"}
    )
    done = line("tool_call", id="c1", action="calendar.create_event", target="Standup", ok=True)

    assert started is not None and done is not None
    assert started.slot == done.slot == "tool:c1"
    assert "calendar.create_event" in started.text
    assert "day=fri" in started.text
    assert "Standup" in done.text


def test_a_failed_tool_says_what_went_wrong():
    failed = line(
        "tool_call", id="c1", action="notion.get_page", ok=False, error="PermissionDenied: no"
    )
    assert failed is not None
    assert "notion.get_page" in failed.text
    assert "PermissionDenied" in failed.text


def test_thinking_is_replaced_by_what_the_model_decided():
    started = line("model_started", turn=1)
    decided = line("generation", output="", tool_calls=["calendar.list_events"])

    assert started is not None and decided is not None
    assert started.slot == decided.slot == "model"
    assert "calendar.list_events" in decided.text


def test_the_answer_so_far_is_a_draft_not_a_step():
    draft = line("answer_draft", text="The next sync is Friday.")
    assert draft is not None
    assert draft.draft is True
    assert draft.slot == "answer"


def test_the_reply_clears_the_thinking_line():
    done = line("reply", turns=2, tools=[])
    assert done is not None
    assert done.clear is True
    assert done.slot == "model"


def test_bookkeeping_events_write_no_line():
    assert line("model_call", turn=1) is None
    assert line("recall", count=0) is None
    assert line("model_error", retryable=False) is None
    assert line("something_new") is None


def test_a_long_result_is_cut_to_the_style():
    long = line("tool_call", id="c1", action="drive.search_files", target="x" * 500, ok=True)
    assert long is not None
    assert len(long.text) < 500


# ---------------------------------------------------------------- the card


def test_the_card_shows_steps_under_a_working_header():
    card = Card()
    started = line("tool_started", id="c1", action="calendar.list_events", arguments={})
    assert started is not None
    card.apply(started)

    body = card.running()
    assert THINKING in body
    assert f"{BULLET}" in body
    assert "calendar.list_events" in body


def test_a_result_writes_over_the_line_that_said_it_started():
    card = Card()
    for name, data in (
        ("tool_started", {"id": "c1", "action": "calendar.list_events", "arguments": {}}),
        (
            "tool_call",
            {"id": "c1", "action": "calendar.list_events", "target": "3 events", "ok": True},
        ),
    ):
        update = progress(name, data, STYLE)
        assert update is not None
        card.apply(update)

    body = card.running()
    assert body.count("calendar.list_events") == 1, "one line, not two"
    assert "3 events" in body
    assert "running" not in body


def test_a_draft_turns_the_header_to_answering_and_is_shown_below_the_steps():
    card = Card()
    draft = line("answer_draft", text="Friday at 5.")
    assert draft is not None
    card.apply(draft)

    body = card.running()
    assert ANSWERING in body
    assert "Friday at 5." in body


def test_the_finished_card_keeps_the_steps_above_the_answer():
    card = Card()
    done = line("tool_call", id="c1", action="calendar.list_events", target="3 events", ok=True)
    assert done is not None
    card.apply(done)

    body = card.finished("There are three events this week.")
    assert "calendar.list_events" in body
    assert body.endswith("There are three events this week.")
    assert THINKING not in body


def test_an_unchanged_line_does_not_dirty_the_card():
    card = Card()
    update = line("tool_started", id="c1", action="drive.search_files", arguments={})
    assert update is not None
    card.apply(update)
    card.dirty = False

    card.apply(update)

    assert card.dirty is False, "the same line again is not an edit"


def test_an_answer_with_no_steps_is_just_the_answer():
    assert Card().finished("  Friday.  ") == "Friday."


# ---------------------------------------------------------------- the sink


def test_the_sink_writes_only_to_the_request_being_watched(ctx):
    from engine.telemetry.progress import ProgressSink

    seen: list[Progress] = []
    sink = ProgressSink()

    # Nobody watching: the event is recorded elsewhere and nothing is written here.
    sink.event(ctx, "model_started", {"turn": 1})
    assert seen == []

    watched = replace(ctx, watcher=seen.append)
    sink.event(watched, "model_started", {"turn": 1})
    sink.event(watched, "model_call", {"turn": 1})

    assert [one.event for one in seen] == ["model_started"], "bookkeeping writes no line"


def test_only_what_discord_calls_an_image_is_sent_as_one():
    """A readable file is still an attachment; it is read into text, never shown to the model."""
    from engine.core.types import Attachment

    png = Attachment.of("https://cdn/one.png", "image/png")
    csv = Attachment.of("https://cdn/sheet.csv", "text/csv")
    assert png is not None and png.is_image
    assert Attachment.of("https://cdn/two.jpg", "image/jpeg; charset=binary") is not None
    assert csv is not None and not csv.is_image
    assert Attachment.accepted([csv], 4) == ()
    assert Attachment.readable([png], 4) == ()


def test_a_type_nothing_handles_is_still_dropped_without_a_word():
    from engine.core.types import Attachment

    assert Attachment.of("https://cdn/thing.exe", "application/x-msdownload") is None
    assert Attachment.of("https://cdn/unknown", "") is None
    assert Attachment.of("", "image/png") is None


def test_no_more_than_max_images_of_one_message_are_sent():
    from engine.core.types import Attachment

    many = [Attachment("https://cdn/x.png", "image/png") for _ in range(10)]
    assert len(Attachment.accepted(many, 4)) == 4
    assert Attachment.accepted(many, 0) == ()
    # The gateway does not trust the platform to have filtered.
    claimed = [Attachment("https://cdn/payload", "text/html")]
    assert Attachment.accepted(claimed, 4) == ()


def test_a_turn_with_images_sends_a_content_array_beside_the_text():
    from engine.core.types import Attachment, ChatMessage, Speaker
    from engine.llm.client import to_wire

    turn = ChatMessage(
        speaker=Speaker.USER,
        content="what is this?",
        images=(Attachment("https://cdn/one.png", "image/png"),),
    )
    body = to_wire(turn)

    assert body["content"] == [
        {"type": "text", "text": "what is this?"},
        {"type": "image_url", "image_url": {"url": "https://cdn/one.png"}},
    ]


def test_a_turn_with_no_images_still_sends_a_plain_string():
    from engine.core.types import ChatMessage, Speaker
    from engine.llm.client import to_wire

    body = to_wire(ChatMessage(speaker=Speaker.USER, content="hi"))
    assert body["content"] == "hi"


# ---------------------------------------------------------------- the turn


class FakeMessage:
    """Enough of discord.Message to record what the card was edited to."""

    def __init__(self, refuse_edit: bool = False) -> None:
        self.edits: list[str] = []
        self._refuse_edit = refuse_edit

    async def edit(self, content: str) -> None:
        if self._refuse_edit:
            raise discord.DiscordException("edit refused")
        self.edits.append(content)


class FakeChannel:
    """Enough of a messageable to post the card, or to refuse it."""

    def __init__(self, refuse: bool = False, refuse_edit: bool = False) -> None:
        self.posted: list[str] = []
        self.message = FakeMessage(refuse_edit)
        self._refuse = refuse

    async def send(self, content: str) -> FakeMessage:
        if self._refuse:
            raise discord.DiscordException("channel refused")
        self.posted.append(content)
        return self.message


def turn_for(channel: FakeChannel, sent: list[Outbound] | None = None) -> Turn:
    async def send(one: Outbound) -> None:
        (sent if sent is not None else []).append(one)

    # No gap, so the editor redraws as soon as the card changes.
    return Turn(channel, 0, send)


def text(body: str) -> Text:
    return Text(ChannelRef(WorkspaceRef("discord", "g1"), "c1"), body)


async def test_the_card_is_posted_before_the_work_starts():
    channel = FakeChannel()
    started: list[str] = []

    async def work(watcher):
        started.append(channel.posted[0] if channel.posted else "")
        return [text("done")]

    assert await turn_for(channel).run(work) is True
    assert started and THINKING in started[0], "the member sees the turn begin"


async def test_the_answer_replaces_the_card():
    channel = FakeChannel()

    async def work(watcher):
        return [text("Friday at 5.")]

    await turn_for(channel).run(work)

    assert channel.message.edits, "the card was edited at the end"
    assert channel.message.edits[-1] == "Friday at 5."


async def test_progress_during_the_work_reaches_the_card():
    channel = FakeChannel()

    async def work(watcher):
        update = progress("tool_started", {"id": "c1", "action": "drive.search_files"}, STYLE)
        assert update is not None
        watcher(update)
        # Let the editor wake and redraw before the work finishes.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        return [text("found it")]

    await turn_for(channel).run(work)

    shown = "\n".join(channel.message.edits)
    assert "drive.search_files" in shown, "the step was drawn while the work ran"


async def test_a_channel_that_refuses_the_card_says_so_rather_than_failing():
    channel = FakeChannel(refuse=True)
    ran = []

    async def work(watcher):
        ran.append(True)
        return [text("done")]

    assert await turn_for(channel).run(work) is False
    assert ran == [], "the caller answers instead; the work is not run twice"


async def test_outbounds_the_card_cannot_carry_are_sent_on_their_own():
    channel = FakeChannel()
    sent: list[Outbound] = []
    second = text("and another thing")

    async def work(watcher):
        return [text("first"), second]

    await turn_for(channel, sent).run(work)

    assert channel.message.edits[-1] == "first"
    assert sent == [second], "the rest posts separately"


async def test_a_card_that_cannot_be_edited_still_posts_the_answer():
    channel = FakeChannel(refuse_edit=True)
    sent: list[Outbound] = []
    answer = text("Friday at 5.")

    async def work(watcher):
        return [answer]

    await turn_for(channel, sent).run(work)

    assert sent == [answer], "the answer is not lost when the edit fails"


async def test_the_editor_stops_when_the_work_raises():
    channel = FakeChannel()

    async def work(watcher):
        raise ZipyError("the gateway gave up")

    with pytest.raises(ZipyError):
        await turn_for(channel).run(work)

    # A leaked editor task would keep redrawing after the turn ended.
    assert all(task.done() for task in asyncio.all_tasks() - {asyncio.current_task()})


# ---------------------------------------------------------------- delegation


def test_a_sub_agent_line_says_how_deep_it_happened():
    from engine.core.types import progress

    step = progress(
        "tool_started",
        {"id": "c1", "action": "github.list_issues", "arguments": {}, "depth": 1, "parent": "d1"},
        STYLE,
    )
    assert step is not None
    assert step.depth == 1
    assert "github.list_issues" in step.text


def test_the_two_levels_do_not_write_over_each_other():
    """Call ids come from the model, so both levels can use the same one."""
    from engine.core.types import progress

    parent = progress("tool_started", {"id": "c1", "action": "a", "arguments": {}}, STYLE)
    sub = progress(
        "tool_started",
        {"id": "c1", "action": "b", "arguments": {}, "depth": 1, "parent": "d1"},
        STYLE,
    )
    assert parent is not None and sub is not None
    assert parent.slot != sub.slot

    card = Card()
    card.apply(parent)
    card.apply(sub)
    body = card.running()
    assert "`a`" in body and "`b`" in body, "two lines, not one written over the other"


def test_a_handoff_shows_the_task_and_is_replaced_by_its_result():
    card = Card()
    for name, data in (
        ("delegate", {"id": "d1", "task": "count the open issues", "tools": ["github"]}),
        ("delegate_done", {"id": "d1", "chars": 42}),
    ):
        update = progress(name, data, STYLE)
        assert update is not None
        card.apply(update)

    body = card.running()
    assert body.count("handed back") == 1
    assert "count the open issues" not in body, "the result wrote over the handoff line"


def test_a_handoff_that_did_not_finish_says_so():
    update = line("delegate_failed", id="d1", error="the subtask ran out of turns")
    assert update is not None
    assert "did not finish" in update.text
    assert "ran out of turns" in update.text


def test_a_sub_agent_step_is_indented_under_the_parent():
    from engine.platforms.cards import INDENT

    card = Card()
    for data in (
        {"id": "c1", "action": "parent.read", "arguments": {}},
        {"id": "c2", "action": "sub.read", "arguments": {}, "depth": 1, "parent": "d1"},
    ):
        update = progress("tool_started", data, STYLE)
        assert update is not None
        card.apply(update)

    body = card.running()
    assert f"{INDENT}" in body
    lines = [one for one in body.splitlines() if "sub.read" in one]
    assert lines and INDENT in lines[0]
    outer = [one for one in body.splitlines() if "parent.read" in one]
    assert outer and INDENT not in outer[0]


def test_an_event_from_the_request_itself_carries_no_depth():
    """The parent's events are byte for byte what they were before delegation existed."""
    from engine.core.types import progress

    step = progress("tool_started", {"id": "c1", "action": "a", "arguments": {}}, STYLE)
    assert step is not None
    assert step.depth == 0
    assert step.slot == "tool:c1"


def test_the_sink_reads_the_level_off_the_context_not_the_event(ctx):
    """Only the orchestrator knows the depth; the llm client and the executor do not."""
    from dataclasses import replace

    from engine.telemetry.progress import ProgressSink

    seen: list[Progress] = []
    sink = ProgressSink()
    nested = replace(ctx, watcher=seen.append, depth=1, parent="d1")

    # An event raised by the llm client, which passes no depth of its own.
    sink.event(nested, "generation", {"output": "", "tool_calls": ["github.list_issues"]})

    assert len(seen) == 1
    assert seen[0].depth == 1, "the sub-agent's model call is marked as one"
    assert seen[0].slot == "d1:model"


def test_the_trace_record_carries_the_level_for_every_layer(ctx):
    """A tool call inside a sub-agent must be distinguishable from the parent's."""
    from dataclasses import replace
    from datetime import UTC, datetime

    from engine.telemetry.trace import record

    flat = record(ctx, "tool_call", {"action": "a"}, datetime.now(UTC))
    assert "depth" not in flat, "the request's own events are what they always were"

    nested = record(
        replace(ctx, depth=1, parent="d1"), "tool_call", {"action": "a"}, datetime.now(UTC)
    )
    assert nested["depth"] == 1
    assert nested["parent"] == "d1"
    assert nested["request_id"] == flat["request_id"], "one file per request, both levels in it"
