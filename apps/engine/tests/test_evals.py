"""The eval suite: the cases, the fixtures, the scoring, and the stack they run on.

None of these need a model. The runner is driven with a scripted model, so the loop is real and
the answers are not.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from engine.core.doubles import ScriptedModel
from engine.core.types import (
    AuditEntry,
    Completion,
    ConfigError,
    Dimension,
    MemberRef,
    OrgId,
    ToolCall,
    ToolError,
)
from engine.evals import fixtures, runner
from engine.evals.cases import Case, Contrast, Suite, load
from engine.evals.scoring import behaviour, correctness, moved
from engine.evals.stack import build
from engine.tools.registry import Registry

ROOT = Path(__file__).resolve().parents[3]
CASES = ROOT / "evals" / "cases.toml"
FIXTURES = ROOT / "evals" / "fixtures.toml"


def entry(action: str) -> AuditEntry:
    """One audit row, which is where a run's calls are read from."""
    return AuditEntry(
        org_id=OrgId("org-1"),
        actor=MemberRef("local", "u1"),
        action=action,
        target="",
        payload={},
        ok=True,
        error="",
        at=datetime.now(UTC),
    )


# ---------------------------------------------------------------- the files


def test_every_case_in_the_repo_loads():
    suite = load(CASES)
    assert suite.cases
    assert len(suite.by_id) == len(suite.cases)


def test_every_case_names_a_story_in_the_user_stories():
    stories = (ROOT / "docs" / "USER_STORIES.md").read_text(encoding="utf-8")
    for case in load(CASES).cases:
        assert f"### {case.id}\n" in stories, f"{case.id} is not a story in docs/USER_STORIES.md"


def test_every_call_a_case_expects_is_a_real_tool_action(cfg):
    registry = Registry(cfg.tools)
    for case in load(CASES).cases:
        for call in case.calls:
            registry.action_type(call)


def test_every_fixture_fits_the_result_model_the_plugin_declares(cfg):
    registry = Registry(cfg.tools)
    answers = dict(fixtures.load(FIXTURES).get("tools", {}))
    for name, answer in answers.items():
        tool, _, action = name.partition(".")
        assert tool in registry.names, f"the fixture {name} names no tool"
        result = registry.tool_class(tool).actions[action].result
        result.model_validate(answer)


def test_every_action_a_case_calls_has_a_fixture():
    answers = dict(fixtures.load(FIXTURES).get("tools", {}))
    for case in load(CASES).cases:
        for call in case.calls:
            assert call in answers, f"{case.id} calls {call}, which no fixture answers"


def test_a_case_without_an_id_says_so(tmp_path):
    path = tmp_path / "cases.toml"
    path.write_text('[[case]]\nask = "when?"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="no id"):
        load(path)


def test_one_id_used_twice_is_refused(tmp_path):
    path = tmp_path / "cases.toml"
    twice = '[[case]]\nid = "a"\nask = "x"\n[[case]]\nid = "a"\nask = "y"\n'
    path.write_text(twice, encoding="utf-8")
    with pytest.raises(ConfigError, match="twice"):
        load(path)


def test_a_contrast_that_names_no_case_is_refused(tmp_path):
    path = tmp_path / "cases.toml"
    path.write_text('[[contrast]]\ncase = "ghost"\ndimension = "depth"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="names no case"):
        load(path)


# ---------------------------------------------------------------- scoring


def test_correctness_is_every_check_and_passes_only_when_all_of_them_do():
    case = Case(id="c", ask="?", calls=("calendar.list_events",), contains=("CPCOM",))
    scored = correctness(case, "It is in CPCOM 210.", ("calendar.list_events",), confirmed=False)
    assert scored.passed
    assert scored.failures() == []


def test_a_run_that_answers_well_without_calling_the_tool_fails():
    case = Case(id="c", ask="?", calls=("calendar.list_events",), contains=("CPCOM",))
    scored = correctness(case, "It is in CPCOM 210.", (), confirmed=False)
    assert not scored.passed
    assert scored.failures() == ["calls"]


def test_a_destructive_case_that_did_not_wait_fails_even_when_the_answer_is_right():
    case = Case(id="c", ask="?", calls=(), contains=(), confirms=True)
    assert correctness(case, "Moved.", (), confirmed=False).failures() == ["confirmed"]


def test_behaviour_is_measured_rather_than_judged():
    read = behaviour("Which one did you mean?", [entry("notion.query_database")])
    assert read.words == 5
    assert read.asked
    assert read.first_call == "notion.query_database"
    assert read.calls == 1


def test_two_runs_that_did_the_same_thing_have_not_moved():
    one = behaviour("Friday at six.", [entry("calendar.list_events")])
    same = behaviour("Friday at six.", [entry("calendar.list_events")])
    longer = behaviour("Friday at six, in CPCOM 210.", [entry("calendar.list_events")])
    assert not moved(one, same)
    assert moved(one, longer)


# ---------------------------------------------------------------- the runner


def _stack(cfg, script):
    """The eval stack with the model scripted, so the loop is real and the answers are not."""
    return build(cfg, fixtures.load(FIXTURES), ScriptedModel(script=list(script)))


async def test_a_run_is_scored_on_what_the_audit_log_says_it_called(cfg):
    call = ToolCall(id="1", name="calendar.list_events", arguments={})
    stack = _stack(cfg, [Completion(text="", tool_calls=(call,)), Completion(text="CPCOM 210.")])
    case = Case(id="calendar-next-meeting", ask="when?", calls=("calendar.list_events",))

    run = await runner.once(stack, case)

    assert run.calls == ("calendar.list_events",)
    assert run.correctness.passed
    assert run.behaviour.first_call == "calendar.list_events"


async def test_a_case_that_asks_for_a_confirmation_is_answered_and_resumed(cfg):
    call = ToolCall(id="1", name="calendar.update_event", arguments={"event_id": "ev-1"})
    stack = _stack(cfg, [Completion(text="", tool_calls=(call,)), Completion(text="Moved it.")])
    case = Case(id="calendar-respace-week", ask="move it", confirms=True)

    run = await runner.once(stack, case)

    assert run.correctness.confirmed
    assert "Moved it." in run.answer


async def test_a_contrast_runs_the_same_case_at_both_ends_and_leaves_no_state_behind(cfg):
    script = [Completion(text="Friday.")] * 2
    stack = _stack(cfg, script)
    suite = Suite(
        cases=(Case(id="c", ask="when?"),),
        contrasts=(Contrast(case="c", dimension=Dimension.DEPTH),),
        by_id={"c": Case(id="c", ask="when?")},
    )

    read = await runner.pair(stack, suite, suite.contrasts[0])

    assert read.held
    assert stack.collaboration.by_member == {}


async def test_an_action_with_no_fixture_says_so_rather_than_answering_something(cfg):
    registry = Registry(cfg.tools)
    replayed = fixtures.replayed(registry.tool_class("calendar"), {})
    tool = replayed(registry.settings_for("calendar"))
    params = registry.tool_class("calendar").actions["list_events"].params

    with pytest.raises(ToolError, match="no fixture for calendar.list_events"):
        await tool.execute("list_events", params.model_construct(), None)


async def test_a_fixture_that_no_longer_fits_the_schema_fails_rather_than_passing(cfg):
    registry = Registry(cfg.tools)
    wrong = {"calendar.list_events": {"events": "not a list of events"}}
    tool = fixtures.replayed(registry.tool_class("calendar"), wrong)(
        registry.settings_for("calendar")
    )
    params = registry.tool_class("calendar").actions["list_events"].params

    with pytest.raises(ConfigError, match="is not a EventList"):
        await tool.execute("list_events", params.model_construct(), None)
