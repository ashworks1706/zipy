"""Recall triggers and the org facts block."""

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
