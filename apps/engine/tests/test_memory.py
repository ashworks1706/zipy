"""Recall triggers and the org facts block."""

import pytest

from engine.core.types import FactCategory, OrgFact
from engine.memory.org_context import render
from engine.memory.triggers import wants_recall


def test_a_question_about_the_past_triggers_recall(cfg):
    triggers = cfg.memory.recall_triggers
    assert wants_recall("What did we  decide about sponsorships?", triggers)
    assert not wants_recall("add an event Friday 3pm", triggers)


def test_facts_are_grouped_by_category_in_a_fixed_order():
    facts = [
        OrgFact(FactCategory.ORG_INFO, "exec board", "meets Fridays at 3pm"),
        OrgFact(FactCategory.TOOL_MAPPING, "budget tracker", "Notion database Finance Tracker"),
    ]
    text = render(facts)
    assert text.index("tool_mapping") < text.index("org_info")
    assert "- budget tracker: Notion database Finance Tracker" in text
    assert render([]) == ""


def test_a_signal_moves_its_dimension_toward_the_target_and_leaves_the_others():
    from engine.core.types import CollaborationState, Dimension, Evidence, MemberRef, Signal
    from engine.core.types.collaboration import NEUTRAL, apply_signals

    member = MemberRef("discord", "u1")
    state = CollaborationState(member=member)
    signal = Signal(Dimension.DEPTH, target=1.0, evidence=Evidence.STATED_PREFERENCE)

    moved = apply_signals(state, [signal], alpha=0.5)

    assert abs(moved.score(Dimension.DEPTH) - 0.75) < 1e-9
    assert moved.score(Dimension.AUTONOMY) == NEUTRAL
    assert moved.observations == 1
    # One observation never decides a dimension.
    assert NEUTRAL < moved.score(Dimension.DEPTH) < 1.0


def test_a_state_says_nothing_until_enough_has_been_observed():
    from engine.core.types import CollaborationState, Dimension, MemberRef
    from engine.memory.collaboration import render

    member = MemberRef("discord", "u1")
    decided = {Dimension.DEPTH: 0.05}

    assert render(CollaborationState(member, decided, observations=4), 5) == ""
    assert "briefly" in render(CollaborationState(member, decided, observations=5), 5)


def test_a_score_near_the_middle_asks_for_nothing():
    from engine.core.types import CollaborationState, Dimension, MemberRef
    from engine.memory.collaboration import render

    member = MemberRef("discord", "u1")
    undecided = {Dimension.DEPTH: 0.5, Dimension.AUTONOMY: 0.55}

    assert render(CollaborationState(member, undecided, observations=50), 5) == ""


def test_every_conditioning_the_config_accepts_has_a_renderer():
    """Config validates against IMPLEMENTED; the renderers are what make it true."""
    from engine.core.types import IMPLEMENTED
    from engine.memory.collaboration import RENDERERS

    assert set(RENDERERS) == set(IMPLEMENTED)


def test_a_conditioning_with_no_renderer_is_refused_at_boot():
    """A prefix needs a server that takes input embeddings; saying so in config must not pass."""
    from engine.core.config import ModelRole
    from engine.core.types import ConfigError

    ModelRole(model="openai/x", conditioning="text")
    with pytest.raises(ConfigError, match="has no renderer yet"):
        ModelRole(model="openai/x", conditioning="prefix")


def test_the_text_renderer_is_what_a_default_role_gets(cfg):
    from engine.core.types import CollaborationState, Conditioning, Dimension, MemberRef
    from engine.memory.collaboration import render, render_text

    assert cfg.models["chat"].conditioning is Conditioning.TEXT
    state = CollaborationState(MemberRef("local", "u1"), {Dimension.DEPTH: 0.1}, observations=9)
    assert render(state, 5) == render_text(state, 5)
    assert "briefly" in render(state, 5)


# ---------------------------------------------------------------- reading a follow-up turn


def _history(*speakers):
    from datetime import UTC, datetime

    from engine.core.types import ChatMessage, Speaker

    return [
        ChatMessage(speaker=Speaker(s), content="x", at=datetime(2026, 9, 18, tzinfo=UTC))
        for s in speakers
    ]


def _read(message, history, cfg):
    from engine.memory import follow_up

    return follow_up.read(
        message,
        history,
        cfg.collaboration.brevity_triggers,
        cfg.collaboration.detail_triggers,
        cfg.collaboration.correction_triggers,
    )


def test_a_turn_that_follows_nothing_is_not_read(cfg):
    """An opening question is a question, not a comment on the last answer."""
    assert _read("why is the meeting Tuesday?", [], cfg) == []
    assert _read("why is the meeting Tuesday?", _history("user"), cfg) == []


def test_asking_for_it_shorter_after_an_answer_moves_depth_down(cfg):
    from engine.core.types import Dimension, Evidence

    signals = _read("just tell me the time", _history("user", "assistant"), cfg)
    assert [s.evidence for s in signals] == [Evidence.ASKED_FOR_BREVITY]
    assert signals[0].dimension is Dimension.DEPTH
    assert signals[0].target == 0.0


def test_asking_for_more_after_an_answer_moves_depth_up(cfg):
    from engine.core.types import Dimension, Evidence

    signals = _read("why did you pick that one?", _history("user", "assistant"), cfg)
    assert [s.evidence for s in signals] == [Evidence.ASKED_FOR_DETAIL]
    assert signals[0].dimension is Dimension.DEPTH
    assert signals[0].target == 1.0


def test_a_correction_moves_autonomy_and_says_nothing_about_length(cfg):
    from engine.core.types import Dimension, Evidence

    signals = _read("no, that's wrong, i meant next week", _history("user", "assistant"), cfg)
    assert [s.evidence for s in signals] == [Evidence.CORRECTED]
    assert signals[0].dimension is Dimension.AUTONOMY
    assert signals[0].target == 0.0


def test_a_turn_that_reads_as_two_things_at_once_raises_nothing(cfg):
    """Ambiguous evidence is worse than none: it moves a dimension on a coin flip."""
    assert _read("explain, but shorter", _history("user", "assistant"), cfg) == []


def test_an_ordinary_follow_up_raises_nothing(cfg):
    assert _read("thanks, book it", _history("user", "assistant"), cfg) == []


def test_a_read_turn_weighs_less_than_a_stated_preference(cfg):
    from engine.core.types import STATED_WEIGHT

    signals = _read("tldr", _history("user", "assistant"), cfg)
    assert 1.0 < signals[0].weight < STATED_WEIGHT


def test_a_turn_is_never_read_while_collaboration_is_off(cfg, ctx):
    """The feature off means the state is not written either, not only not read."""
    import asyncio

    from engine.core.doubles import (
        FixedEmbedder,
        MemoryCollaboration,
        MemoryConversation,
        MemoryDocuments,
        MemoryOrgContext,
    )
    from engine.core.types import ChatMessage, Speaker
    from engine.memory.manager import MemoryManager

    collaboration = MemoryCollaboration()
    conversation = MemoryConversation()
    conversation.channels[ctx.channel] = [ChatMessage(speaker=Speaker.ASSISTANT, content="a")]
    manager = MemoryManager(
        memory=cfg.memory,
        conversation=conversation,
        org_context=MemoryOrgContext(),
        embedder=FixedEmbedder([0.1]),
        documents=MemoryDocuments(),
        collaboration=collaboration,
        settings=cfg.collaboration,
    )
    asyncio.run(manager.build(ctx, "just tell me"))
    assert collaboration.by_member == {}


def test_a_follow_up_is_recorded_when_collaboration_is_on(cfg, ctx):
    import asyncio

    from engine.core.doubles import (
        FixedEmbedder,
        MemoryCollaboration,
        MemoryConversation,
        MemoryDocuments,
        MemoryOrgContext,
    )
    from engine.core.types import ChatMessage, Dimension, Speaker
    from engine.memory.manager import MemoryManager

    collaboration = MemoryCollaboration()
    conversation = MemoryConversation()
    conversation.channels[ctx.channel] = [ChatMessage(speaker=Speaker.ASSISTANT, content="a")]
    manager = MemoryManager(
        memory=cfg.memory,
        conversation=conversation,
        org_context=MemoryOrgContext(),
        embedder=FixedEmbedder([0.1]),
        documents=MemoryDocuments(),
        collaboration=collaboration,
        settings=cfg.collaboration.model_copy(update={"enabled": True}),
    )
    asyncio.run(manager.build(ctx, "just tell me"))
    state = collaboration.by_member[(ctx.org_id, ctx.member)]
    assert state.score(Dimension.DEPTH) < 0.5
    assert state.observations == 1


def test_a_follow_up_reads_the_same_whether_the_platform_includes_this_turn(cfg):
    """Local appends the turn before dispatch; Discord need not. Both must read alike."""
    without = _history("user", "assistant")
    with_it = _history("user", "assistant", "user")
    assert _read("tldr", without, cfg) == _read("tldr", with_it, cfg)
    assert _read("tldr", with_it, cfg) != []


def test_an_opening_turn_is_still_not_a_follow_up_when_the_platform_includes_it(cfg):
    assert _read("why is it Tuesday?", _history("user"), cfg) == []


def test_only_an_answer_counts_as_the_thing_being_followed(cfg):
    """Platform history holds what was posted; anything else in that slot is not an answer."""
    assert _read("tldr", _history("user", "assistant", "tool", "user"), cfg) == []
