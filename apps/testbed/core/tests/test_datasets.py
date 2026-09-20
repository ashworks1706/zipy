"""The dataset pipeline: export from traces, redaction, verification, and the ledger."""

import io
import json

import pytest
from rich.console import Console

from testbed.core.settings import Config
from testbed.core.types import TrainingError, TrainingExample
from testbed.datasets import curate, export, redact, review, verify
from testbed.posttrain import sft

GENERATION = {
    "at": "2026-09-18T02:00:00+00:00",
    "request_id": "req-1",
    "org_id": "org-1",
    "platform": "discord",
    "event": "generation",
    "data": {
        "model": "gpt-4o",
        "input": [
            {"role": "system", "content": "You are Zipy."},
            {"role": "user", "content": "when is the exec meeting?"},
        ],
        "output": "Wednesday at 6pm.",
        "tool_calls": [],
    },
}


def _trace(tmp_path, *records):
    """One request's trace file, under the org directory the engine writes."""
    directory = tmp_path / "org-1"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "req-1.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return path


def _example(id_="req-1:0", question="q", reply="a", tool_calls=None):
    return TrainingExample(
        id=id_,
        messages=[
            {"role": "system", "content": "s"},
            {"role": "user", "content": question},
        ],
        reply=reply,
        tool_calls=tool_calls or [],
    )


# ---------------------------------------------------------------- export


def test_a_generation_in_a_trace_becomes_a_training_example(tmp_path):
    _trace(tmp_path, GENERATION)
    examples = export.export(tmp_path)
    assert len(examples) == 1
    assert examples[0].id == "req-1:0"
    assert examples[0].reply == "Wednesday at 6pm."
    assert examples[0].org_id == "org-1"
    assert examples[0].platform == "discord"
    assert [m["role"] for m in examples[0].messages] == ["system", "user"]


def test_events_that_are_not_generations_are_not_examples(tmp_path):
    _trace(tmp_path, {"event": "tool_call", "data": {}}, GENERATION, {"event": "reply", "data": {}})
    assert len(export.export(tmp_path)) == 1


def test_several_generations_in_one_request_are_numbered_in_order(tmp_path):
    second = {**GENERATION, "data": {**GENERATION["data"], "output": "second"}}
    _trace(tmp_path, GENERATION, second)
    assert [e.id for e in export.export(tmp_path)] == ["req-1:0", "req-1:1"]


def test_a_line_that_is_not_json_does_not_stop_the_export(tmp_path):
    directory = tmp_path / "org-1"
    directory.mkdir(parents=True)
    (directory / "req-1.jsonl").write_text("not json\n" + json.dumps(GENERATION) + "\n")
    assert len(export.export(tmp_path)) == 1


def test_a_directory_with_no_traces_exports_nothing(tmp_path):
    assert export.export(tmp_path) == []


def test_the_tool_calls_a_reply_asked_for_survive_the_export(tmp_path):
    call = {
        "id": "c1",
        "type": "function",
        "function": {"name": "calendar__list_events", "arguments": '{"days": 7}'},
    }
    with_calls = {**GENERATION, "data": {**GENERATION["data"], "tool_calls": [call]}}
    _trace(tmp_path, with_calls)
    assert export.export(tmp_path)[0].tool_calls == [call]


# ---------------------------------------------------------------- redaction


def test_redaction_covers_the_people_in_the_messages():
    text = "mail ash@asu.edu call 480-555-1234 ping <@1234567890123456789>"
    out = redact.redact_text(text)
    assert "ash@asu.edu" not in out and "[email]" in out
    assert "555-1234" not in out and "[phone]" in out
    assert "1234567890123456789" not in out


def test_redaction_reaches_inside_messages_and_tool_call_arguments():
    call = {"function": {"name": "mail", "arguments": '{"to": "ash@asu.edu"}'}}
    example = _example(
        question="write to ash@asu.edu", reply="sent to ash@asu.edu", tool_calls=[call]
    )
    cleaned = redact.redact(example)
    assert "ash@asu.edu" not in json.dumps(cleaned.model_dump(mode="json"))


# ---------------------------------------------------------------- verification


def test_verify_drops_the_malformed_the_empty_and_the_duplicates():
    empty = _example(id_="b", reply="")
    no_system = TrainingExample(id="c", messages=[{"role": "user", "content": "q"}], reply="a")
    kept, reasons = verify.verify([_example(), _example(id_="dup"), empty, no_system])
    assert [e.id for e in kept] == ["req-1:0"]
    assert reasons == {"duplicate": 1, "empty reply": 1, "first message is not system": 1}


def test_a_reply_that_only_calls_a_tool_is_not_empty():
    call = {"function": {"name": "calendar__list_events", "arguments": "{}"}}
    kept, _ = verify.verify([_example(reply="", tool_calls=[call])])
    assert len(kept) == 1


def test_a_tool_call_without_a_name_is_dropped():
    _, reasons = verify.verify([_example(reply="", tool_calls=[{"function": {}}])])
    assert reasons == {"tool call without a name": 1}


# ---------------------------------------------------------------- the ledger


def test_an_example_nobody_judged_does_not_reach_the_training_set():
    ledger = curate.Ledger()
    accepted, counts = curate.apply([_example()], ledger)
    assert accepted == []
    assert counts["unreviewed"] == 1


def test_a_kept_example_reaches_the_training_set_unchanged():
    example = _example()
    ledger = curate.Ledger()
    ledger.record(curate.decide(example, "keep", "", "ash"))
    accepted, counts = curate.apply([example], ledger)
    assert accepted == [example]
    assert counts["kept"] == 1
    assert curate.pending([example], ledger) == []


def test_a_fixed_example_trains_on_the_reply_the_reviewer_wrote():
    example = _example(reply="Tuesdays.")
    decision = curate.decide(example, "fix", "wrong day", "ash")
    decision.reply = "Wednesdays at 6pm."
    ledger = curate.Ledger()
    ledger.record(decision)
    accepted, counts = curate.apply([example], ledger)
    assert accepted[0].reply == "Wednesdays at 6pm."
    assert accepted[0].messages == example.messages
    assert counts["fixed"] == 1


def test_an_example_that_changed_under_its_decision_is_stale():
    example = _example()
    ledger = curate.Ledger()
    ledger.record(curate.decide(example, "keep", "", "ash"))
    accepted, counts = curate.apply([_example(reply="something else")], ledger)
    assert accepted == []
    assert counts["stale"] == 1


def test_the_ledger_round_trips_through_a_file(tmp_path):
    path = tmp_path / "decisions.jsonl"
    ledger = curate.Ledger()
    ledger.record(curate.decide(_example(), "drop", "off topic", "ash"))
    curate.save(path, ledger)
    back = curate.load(path)
    assert back.get("req-1:0").reason == "off topic"
    assert back.counts() == {"keep": 0, "drop": 1, "fix": 0}


def test_judging_one_example_twice_keeps_only_the_last_word():
    example = _example()
    ledger = curate.Ledger()
    ledger.record(curate.decide(example, "keep", "", "ash"))
    ledger.record(curate.decide(example, "drop", "changed my mind", "ash"))
    assert len(ledger.decisions) == 1
    assert curate.apply([example], ledger)[1]["dropped"] == 1


# ---------------------------------------------------------------- the review loop


def test_the_reviewer_sees_the_question_and_the_calls():
    call = {"function": {"name": "calendar__list_events", "arguments": '{"days": 7}'}}
    example = _example(question="what is on this week?", tool_calls=[call])
    assert review.question(example) == "what is on this week?"
    assert "calendar__list_events(" in review.calls(example)


def test_a_question_asked_with_an_image_still_reads_as_text():
    example = TrainingExample(
        id="a",
        messages=[
            {"role": "system", "content": "s"},
            {"role": "user", "content": [{"type": "text", "text": "what is this?"}]},
        ],
        reply="a poster",
    )
    assert review.question(example) == "what is this?"


def test_every_key_the_prompt_offers_is_an_answer_and_survives_rich():
    console = Console(file=io.StringIO(), width=100)
    console.print(review.PROMPT)
    printed = console.file.getvalue()
    for key, word in review.ANSWERS.items():
        assert review.answer(Console(), key) == word
        assert f"({key})" in review.PROMPT
        assert key in printed


def _editor(tmp_path, body):
    script = tmp_path / "editor.sh"
    script.write_text(f'#!/bin/sh\nprintf %s "{body}" > "$1"\n')
    script.chmod(0o755)
    return str(script)


def test_a_fix_reads_back_what_the_editor_wrote(tmp_path, monkeypatch):
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setenv("EDITOR", _editor(tmp_path, "Wednesdays."))
    assert review.edit("Tuesdays.") == "Wednesdays."


def test_leaving_the_editor_unchanged_judges_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setenv("EDITOR", _editor(tmp_path, "same"))
    assert review.edit("same") is None


def test_an_editor_that_cannot_run_is_no_edit(monkeypatch):
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setenv("EDITOR", "/nonexistent/editor")
    assert review.edit("anything") is None


# ---------------------------------------------------------------- settings and training


def test_the_settings_read_the_repo_toml(monkeypatch):
    monkeypatch.setenv("ZIPY_CONFIG_FILE", "zipy.toml")
    cfg = Config(_env_file=None)
    assert cfg.training.data_dir.name == "training"
    assert cfg.training.training_path.name == "sft.jsonl"
    assert cfg.training.verified_path != cfg.training.training_path
    assert str(cfg.traces_dir).endswith("traces")


def test_a_negative_age_is_refused(monkeypatch):
    monkeypatch.setenv("ZIPY_CONFIG_FILE", "zipy.toml")
    monkeypatch.setenv("ZIPY_TRAINING__MAX_AGE_DAYS", "-1")
    with pytest.raises(TrainingError, match="max_age_days"):
        Config(_env_file=None)


def test_the_committed_train_config_loads_and_reads_the_curated_set():
    from pathlib import Path

    cfg = sft.load_config(Path("apps/testbed/configs/train/sft.yaml"))
    assert cfg.dataset.name == "sft.jsonl"
    assert cfg.train.epochs > 0


def test_a_conversation_is_the_messages_plus_the_reply():
    call = {"function": {"name": "calendar__list_events", "arguments": "{}"}}
    turns = sft.conversation(_example(reply="Wednesday.", tool_calls=[call]))
    assert [t["role"] for t in turns] == ["system", "user", "assistant"]
    assert turns[-1]["content"] == "Wednesday."
    assert turns[-1]["tool_calls"] == [call]


def test_training_on_a_dataset_that_does_not_exist_names_the_step_that_makes_it(tmp_path):
    with pytest.raises(TrainingError, match="data export"):
        sft.load_examples(tmp_path / "sft.jsonl")


def test_training_on_an_empty_dataset_says_nothing_was_accepted(tmp_path):
    path = tmp_path / "sft.jsonl"
    path.write_text("")
    with pytest.raises(TrainingError, match="accepted by a reviewer"):
        sft.load_examples(path)
