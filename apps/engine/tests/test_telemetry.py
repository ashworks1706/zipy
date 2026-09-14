"""Trace files, the fan-out, and the metrics registry."""

import json

from engine.core.doubles import MemoryTrace
from engine.telemetry.metrics import Metrics
from engine.telemetry.trace import Fanout, JsonlTrace


def test_each_request_gets_its_own_trace_file_under_its_org(tmp_path, ctx):
    sink = JsonlTrace(tmp_path)
    sink.event(ctx, "model_call", {"role": "chat", "tokens": 120})
    sink.event(ctx, "tool_call", {"tool": "calendar.list_events", "ok": True})
    lines = sink.path(ctx).read_text().splitlines()
    assert sink.path(ctx) == tmp_path / "org-1" / "req-1.jsonl"
    assert [json.loads(line)["event"] for line in lines] == ["model_call", "tool_call"]
    assert json.loads(lines[0])["platform"] == "discord"


def test_an_unwritable_trace_directory_never_fails_the_request(tmp_path, ctx):
    blocker = tmp_path / "file"
    blocker.write_text("")
    JsonlTrace(blocker).event(ctx, "model_call", {})


def test_the_fanout_reaches_every_sink(ctx):
    first, second = MemoryTrace(), MemoryTrace()
    Fanout([first, second]).event(ctx, "reply", {"chars": 10})
    assert first.events == second.events == [("reply", {"chars": 10})]


def test_metrics_are_labelled_by_plugin_and_never_by_org():
    metrics = Metrics()
    metrics.tool_calls.labels(tool="calendar", action="create_event", outcome="ok").inc()
    metrics.tokens.labels(role="chat", kind="prompt").inc(120)
    snapshot = metrics.snapshot()
    assert snapshot["zipy_tool_calls_total{action=create_event,outcome=ok,tool=calendar}"] == 1
    assert snapshot["zipy_tokens_total{kind=prompt,role=chat}"] == 120
    body, content_type = metrics.exposition()
    assert b"zipy_tool_calls_total" in body and content_type.startswith("text/plain")
    assert "org" not in body.decode()


def test_two_registries_never_share_counts():
    a, b = Metrics(), Metrics()
    a.jobs.labels(kind="sync:drive", outcome="ok").inc()
    assert "zipy_jobs_total{kind=sync:drive,outcome=ok}" not in b.snapshot()
