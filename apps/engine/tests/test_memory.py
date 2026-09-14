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
