"""The developer console: catalog, command line, logs, status parsing, runner, and the app."""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
from datetime import datetime
from pathlib import Path

import pytest

from cli.chat import Transcript, Turn, decode
from cli.core.config import Config
from cli.logs import LogBuffer, LogLine, LogWriter, log_name
from cli.meters import Meters, spark
from cli.runner import Runner
from cli.status import Snapshot, parse_compose_ps, traces
from cli.units import Command, Group, Kind, Unit, catalog, parse_command

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def cfg(monkeypatch) -> Config:
    monkeypatch.setenv("ZIPY_CONFIG_FILE", str(ROOT / "zipy.toml"))
    monkeypatch.setenv("ZIPY_CONSOLE__SPLASH", "false")
    return Config(_env_file=None)


def _recipes() -> set[str]:
    text = (ROOT / "justfile").read_text()
    names = set(re.findall(r"^([a-z][\w-]*)(?:\s[^:\n]*)?:(?!=)", text, re.MULTILINE))
    return names | set(re.findall(r"^alias ([\w-]+) :=", text, re.MULTILINE))


def test_every_catalog_unit_is_a_just_recipe():
    recipes = _recipes()
    for unit in catalog():
        assert unit.args[0] in recipes, unit.id


def test_every_service_unit_is_a_compose_service():
    compose = (ROOT / "deploy" / "compose.yml").read_text()
    for unit in catalog():
        if unit.kind is Kind.SERVICE:
            assert re.search(rf"^  {re.escape(unit.service)}:$", compose, re.MULTILINE), unit.id


def test_catalog_ids_are_unique_and_there_is_one_agent():
    units = catalog()
    ids = [u.id for u in units]
    assert len(ids) == len(set(ids))
    assert [u.id for u in units if u.kind is Kind.AGENT] == ["chat --jsonl"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("q", Command("quit")),
        ("help", Command("help")),
        ("clear", Command("clear")),
        ("start check", Command("start", arg="check")),
        ("restart serve", Command("restart", arg="serve")),
        ("just traces", Command("just", args=("traces",))),
        ("traces abc", Command("just", args=("traces", "abc"))),
        ("", Command("none")),
    ],
)
def test_command_line_parsing(text, expected):
    assert parse_command(text) == expected


def _line(text: str) -> LogLine:
    return LogLine(datetime(2026, 1, 1), "out", text)


def test_the_log_buffer_keeps_the_newest_lines_and_searches_both_ways():
    buffer = LogBuffer(3)
    for i in range(5):
        buffer.append(_line(f"line {i}"))
    assert [line.text for line in buffer.window(0, 10)] == ["line 2", "line 3", "line 4"]
    buffer = LogBuffer(10)
    for text in ("alpha", "Beta", "gamma", "beta"):
        buffer.append(_line(text))
    assert buffer.find("beta", 0) == 1
    assert buffer.find("beta", 0, backwards=True) == 3
    assert buffer.find("delta", 0) is None


def test_log_files_are_named_by_unit_and_appended(tmp_path):
    writer = LogWriter(tmp_path)
    writer.append("test integration", _line("hello"))
    writer.close()
    assert (tmp_path / log_name("test integration")).read_text().endswith("out hello\n")
    assert len(log_name("x" * 500)) == 124


def test_compose_ps_tells_a_running_service_from_one_still_starting():
    rows = [
        '{"Service":"postgres","State":"running","Health":"starting"}',
        '{"Service":"langfuse","State":"restarting","Health":""}',
        '{"Service":"redis","State":"running","Health":"healthy"}',
        '{"Service":"grafana","State":"exited","Health":""}',
    ]
    assert parse_compose_ps("\n".join(rows)) == {
        "postgres": "starting",
        "langfuse": "restarting",
        "redis": "running",
    }
    assert parse_compose_ps('[{"Service":"redis","State":"running"}]') == {"redis": "running"}
    assert parse_compose_ps("not json") == {}


def test_the_newest_trace_is_the_last_trace(tmp_path):
    assert traces(tmp_path) == (0, "")
    (tmp_path / "org-1").mkdir()
    (tmp_path / "org-1" / "abcdef123456.jsonl").write_text(
        '{"at": "2026-09-13T14:02:11+00:00", "event": "reply"}\n'
    )
    assert traces(tmp_path) == (1, "abcdef12 14:02:11")


def test_the_console_reads_only_its_keys_from_the_shared_file(tmp_path, monkeypatch):
    path = tmp_path / "zipy.toml"
    path.write_text(
        "[console]\nlog_lines = 7\n[platforms.discord]\nenabled = true\n"
        "[platforms.slack]\nenabled = false\n[agent]\nmax_iterations = 3\n"
    )
    monkeypatch.setenv("ZIPY_CONFIG_FILE", str(path))
    cfg = Config(_env_file=None)
    assert cfg.console.log_lines == 7
    assert cfg.enabled_platforms == ["discord"]


def test_zipy_chat_lines_become_turns_and_log_lines():
    t = Transcript()
    assert decode("plain text") is None and decode('{"no": "type"}') is None
    assert t.apply({"type": "ready"}) == "ready"
    t.ask("hi")
    event = {"event": "tool_call", "data": {"tool": "calendar.list_events", "arguments": {}}}
    assert t.apply({"type": "event", "event": event}) == "tool_call tool=calendar.list_events"
    assert t.waiting and t.activity == "tool call"
    result = {
        "conversation_id": "c9",
        "request_id": "r1234567890",
        "answer": "Exec board meets Friday at 3pm.",
        "tool_calls": 2,
        "usage": {"prompt_tokens": 3, "completion_tokens": 4, "cost_cents": 0.02},
        "duration_ms": 2500,
    }
    t.apply({"type": "result", "result": result})
    assert not t.waiting and t.session == "c9"
    assert t.turns[-1] == Turn(
        "agent",
        "Exec board meets Friday at 3pm.",
        "2 tool calls · 7 tokens · 0.02c · 2.5s · r1234567",
    )
    held = result | {
        "answer": "",
        "confirmation": {"action": "calendar.delete_event", "summary": "Delete Exec Board"},
    }
    t.apply({"type": "result", "result": held})
    assert t.pending == "calendar.delete_event: Delete Exec Board"
    assert t.turns[-1].text == "waiting for your confirmation"
    t.confirming(approve=True)
    assert t.pending is None and t.waiting
    t.restarted()
    assert t.session is None and not t.ready and t.turns[-1].role == "note"
    t.apply({"type": "error", "message": "nope"})
    assert t.turns[-1] == Turn("note", "nope") and not t.waiting


def test_the_metrics_pane_reads_zipy_counters_and_sparks_the_rates():
    assert spark([0, 1, 2], 10) == "▁▅█"
    m = Meters()
    counted = {
        "zipy_messages_total{outcome=replied,platform=local}": 1.0,
        "zipy_tokens_total{kind=prompt,role=chat}": 100.0,
        "zipy_model_call_seconds_sum{role=chat}": 2.0,
        "zipy_model_call_seconds_count{role=chat}": 2.0,
    }
    m.update(counted)
    assert not m.rates
    m.update(counted | {"zipy_messages_total{outcome=replied,platform=local}": 3.0})
    assert list(m.rates["zipy_messages_total"]) == [2.0]
    assert m.split("zipy_tokens_total", "kind") == {"prompt": 100.0}
    assert m.mean("zipy_model_call_seconds") == "1.0s"
    body = m.render(80).plain
    assert "local 3" in body and "prompt 100" in body
    assert Meters().render(80).plain == "waiting for the agent"


def _collect(tmp_path, script: str, stop_after: float | None = None):
    lines: list[tuple[str, str]] = []
    codes: list[int | None] = []

    async def scenario() -> None:
        done = asyncio.Event()

        def on_exit(_unit: str, code: int | None) -> None:
            codes.append(code)
            done.set()

        runner = Runner(tmp_path, lambda _u, s, t: lines.append((s, t)), on_exit, ("sh", "-c"))
        await runner.start("u", [script])
        if stop_after is not None:
            await asyncio.sleep(stop_after)
            assert runner.stop("u")
        await asyncio.wait_for(done.wait(), timeout=10)
        assert not runner.owns("u")

    asyncio.run(scenario())
    return lines, codes


def test_the_runner_streams_both_outputs_and_the_exit_code(tmp_path):
    lines, codes = _collect(tmp_path, "echo hello; echo oops >&2; exit 3")
    assert ("out", "hello") in lines and ("err", "oops") in lines
    assert lines[0][0] == "meta" and codes == [3]


def test_stopping_kills_the_whole_process_group(tmp_path):
    lines, codes = _collect(tmp_path, "sleep 30 & sleep 30; echo never", stop_after=0.3)
    assert codes and codes[0] != 0
    assert ("out", "never") not in lines


# ---------- the app, driven headless ----------


def _snapshot(_cfg) -> Snapshot:
    return Snapshot(platforms=("discord",), engine_up=False, traces=0, last_trace="", git="abc1234")


def _app(cfg, tmp_path, *units: Unit, launcher=("sh", "-c"), probe=_snapshot):
    from cli.app import ConsoleApp

    return ConsoleApp(cfg, tmp_path, units=list(units), launcher=launcher, probe=probe)


async def _until(pilot, condition, timeout: float = 20.0) -> None:
    for _ in range(int(timeout / 0.05)):
        if condition():
            return
        await pilot.pause(0.05)
    raise AssertionError("condition not met in time")


def _tasks(*scripts: str) -> list[Unit]:
    return [Unit(Group.GATE, (s,), f"hint {i}") for i, s in enumerate(scripts)]


def test_enter_runs_the_selected_unit_and_streams_its_output(cfg, tmp_path):
    from cli.app import Status

    async def scenario() -> None:
        app = _app(cfg, tmp_path, *_tasks("echo first", "echo second"))
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.press("j", "enter")
            await _until(pilot, lambda: app.states[1].status is Status.OK)
            texts = [line.text for line in app.states[1].logs.window(0, 10)]
            assert "second" in texts and texts[-1] == "exited with code 0"
            assert app.states[0].status is Status.IDLE
        assert (tmp_path / cfg.console.log_dir / log_name("echo second")).exists()

    asyncio.run(scenario())


def test_x_stops_a_running_unit_and_a_failure_is_marked(cfg, tmp_path):
    from cli.app import Status

    async def scenario() -> None:
        app = _app(cfg, tmp_path, *_tasks("sleep 30", "exit 2"))
        async with app.run_test() as pilot:
            await pilot.press("enter")
            await _until(pilot, lambda: app.runner.owns("sleep 30"))
            await pilot.press("x")
            await _until(pilot, lambda: not app.runner.owns("sleep 30"))
            assert app.states[0].status is Status.IDLE
            await pilot.press("j", "enter")
            await _until(pilot, lambda: app.states[1].status is Status.FAILED)
            assert app.states[1].code == 2

    asyncio.run(scenario())


def test_the_command_line_search_and_help(cfg, tmp_path):
    from cli.app import Mode, Pane, Status

    async def scenario() -> None:
        app = _app(cfg, tmp_path, *_tasks("printf 'a\\nne%sle\\nb\\n' ed"))
        async with app.run_test() as pilot:
            await pilot.press("enter")
            await _until(pilot, lambda: app.states[0].status is Status.OK)
            await pilot.press("slash", *"needle", "enter")
            assert app.key_mode is Mode.NORMAL and app.pane is Pane.LOGS
            assert app.states[0].logs.window(app.hit or 0, 1)[0].text == "needle"
            await pilot.press("colon", *"clear", "enter")
            assert len(app.states[0].logs) == 0
            await pilot.press("question_mark")
            assert app.show_help
            await pilot.press("j")
            assert not app.show_help
            await pilot.press("colon", *"echo", "enter")
            assert app.states[-1].unit.group is Group.ADHOC

    asyncio.run(scenario())


def test_the_terminal_comes_back_after_htop_exits(cfg, tmp_path):
    async def scenario() -> None:
        app = _app(cfg, tmp_path, *_tasks("true"), launcher=("echo",))
        app.suspend = contextlib.nullcontext
        async with app.run_test() as pilot:
            await pilot.press("t")
            assert app.notice == "" and not app._handed_over

    asyncio.run(scenario())


def test_a_service_row_starts_and_stops_that_service(cfg, tmp_path):
    from dataclasses import replace

    running: set[str] = set()

    def probe(config):
        return replace(_snapshot(config), services={name: "running" for name in running})

    async def scenario() -> None:
        unit = Unit(Group.SERVICES, ("logs", "redis"), "hint", Kind.SERVICE, "redis", "redis")
        app = _app(cfg, tmp_path, unit, launcher=("echo",), probe=probe)
        async with app.run_test() as pilot:
            await pilot.press("enter")
            await _until(pilot, lambda: "up redis" in _texts(app))
            running.add("redis")
            await _until(pilot, lambda: "logs redis" in _texts(app))
            await pilot.press("enter")
            await _until(pilot, lambda: "stop redis" in _texts(app))

    asyncio.run(scenario())


def _texts(app):
    return [line.text for line in app.states[0].logs.window(0, 60)]


# Speaks the zipy chat --jsonl protocol: an answer, or a held action and then its outcome.
FAKE_ZIPY = """
answer='{"type":"result","result":{"conversation_id":"c1","request_id":"r1","answer":"Friday 3pm",
"tool_calls":1,"usage":{"prompt_tokens":5,"completion_tokens":2},"duration_ms":1200}}'
held='{"type":"result","result":{"conversation_id":"c1","request_id":"r2","answer":"",
"tool_calls":0,"usage":{},"duration_ms":10,
"confirmation":{"action":"calendar.delete_event","summary":"x"}}}'
done='{"type":"result","result":{"conversation_id":"c1","request_id":"r3","answer":"deleted",
"tool_calls":1,"usage":{},"duration_ms":10}}'
event='{"type":"event","event":{"event":"model_call","data":{"role":"chat"}}}'
counted='{"type":"stats","stats":{"zipy_messages_total{outcome=replied,platform=local}":2}}'
echo '{"type":"ready"}'
while read -r line; do
  case "$line" in
    *stats*) echo $counted ;;
    *confirm*) echo $done ;;
    *delete*) echo $event; echo $held ;;
    *) echo $event; echo $answer ;;
  esac
done
"""


def test_zipy_chat_starts_with_the_console_and_answers_in_the_chat(cfg, tmp_path):
    from cli.app import Mode

    async def scenario() -> None:
        unit = Unit(Group.SERVICES, (FAKE_ZIPY,), "hint", Kind.AGENT, "zipy")
        app = _app(cfg, tmp_path, unit)
        async with app.run_test(size=(140, 30)) as pilot:
            await _until(pilot, lambda: app.transcript.ready)
            await pilot.press("i", *"exec board?", "enter")
            assert app.key_mode is Mode.CHAT
            await _until(pilot, lambda: not app.transcript.waiting)
            assert [(t.role, t.text) for t in app.transcript.turns] == [
                ("you", "exec board?"),
                ("agent", "Friday 3pm"),
            ]
            await _until(pilot, lambda: app.meters.latest)
            assert app.meters.total("zipy_messages_total") == 2
            await pilot.press(*" delete it", "enter")
            await _until(pilot, lambda: app.transcript.pending is not None)
            await pilot.press(*"more", "enter")
            assert "holding an action" in app.notice
            await pilot.press("ctrl+u", "escape", "a")
            await _until(pilot, lambda: app.transcript.turns[-1].text == "deleted")
            assert app.transcript.pending is None

    asyncio.run(scenario())


def test_the_logo_animation_settles_on_the_logo_at_one_size():
    from cli.logo import animation

    frames, logo = animation()
    assert len(frames) == 5 and all(f.seconds > 0 for f in frames)
    assert frames[3].text == logo
    assert frames[4].text.strip() == ""
    rows = logo.split("\n")
    assert len(rows) == 13 and max(len(r) for r in rows) == 59
    assert all(len(f.text.split("\n")) <= 13 for f in frames)


def test_the_website_frames_are_generated_from_the_same_exports():
    from cli.logo import animation

    _, logo = animation()
    generated = (ROOT / "apps" / "website" / "lib" / "cli-frames.ts").read_text()
    assert json.dumps(logo, ensure_ascii=False) in generated, "run: just web-frames"


def test_the_splash_plays_then_hands_over_and_a_key_skips_it(cfg, tmp_path, monkeypatch):
    from cli.splash import Splash

    async def scenario(skip: bool) -> None:
        cfg.console.splash = True
        app = _app(cfg, tmp_path, *_tasks("true"))
        async with app.run_test(size=(100, 30)) as pilot:
            await _until(pilot, lambda: isinstance(app.screen, Splash))
            if skip:
                await pilot.press("space")
            await _until(pilot, lambda: not isinstance(app.screen, Splash), timeout=5)
            await pilot.press("j")
            assert app.selected == 0

    asyncio.run(scenario(skip=False))
    asyncio.run(scenario(skip=True))
