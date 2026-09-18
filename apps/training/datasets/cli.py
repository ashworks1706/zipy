"""data export, data verify, data review, data curate, data stats."""

from __future__ import annotations

import json
import os
from pathlib import Path

import typer
from rich.console import Console

from training.core.settings import load
from training.core.types import TrainingError, TrainingExample
from training.datasets import curate, export, redact, review, verify

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()
err = Console(stderr=True)


def fail(exc: Exception) -> typer.Exit:
    """Print an error without a traceback and exit 1."""
    err.print("[red]error[/red] ", end="")
    err.print(str(exc), markup=False, highlight=False)
    return typer.Exit(1)


def _read(path: Path) -> list[TrainingExample]:
    """Every example in a JSONL file. A missing file is an error naming the step before it."""
    if not path.exists():
        raise TrainingError(f"{path} does not exist yet; run the step before this one")
    return [
        TrainingExample.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write(path: Path, examples: list[TrainingExample]) -> None:
    """Write examples as JSONL, making the directory when it is missing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(example.model_dump_json() + "\n" for example in examples), encoding="utf-8"
    )


@app.callback()
def main() -> None:
    """Datasets from real runs."""


@app.command("export")
def export_cmd(
    traces: Path = typer.Option(None, help="Defaults to telemetry.trace_dir."),
    out: Path = typer.Option(None, help="Defaults under training.data_dir."),
    days: int = typer.Option(None, help="Skip traces older than this. 0 reads every one."),
) -> None:
    """Read every generation the engine traced, redact it, and write the raw examples."""
    cfg = load()
    traces = traces or cfg.traces_dir
    out = out or cfg.training.raw_path
    days = cfg.training.max_age_days if days is None else days
    if not traces.exists():
        raise fail(TrainingError(f"no traces under {traces}; run zipy and ask it something first"))
    examples = [redact.redact(example) for example in export.export(traces, days)]
    _write(out, examples)
    console.print(f"[green]{len(examples)}[/green] examples -> {out}")


@app.command("verify")
def verify_cmd(
    src: Path = typer.Option(None, help="Defaults to the raw examples."),
    out: Path = typer.Option(None, help="Defaults under training.data_dir."),
) -> None:
    """Drop the malformed and the duplicates; write the set a reviewer sees."""
    cfg = load()
    try:
        examples = _read(src or cfg.training.raw_path)
    except TrainingError as exc:
        raise fail(exc) from exc
    out = out or cfg.training.verified_path
    kept, reasons = verify.verify(examples)
    _write(out, kept)
    console.print(f"kept [green]{len(kept)}[/green] -> {out}")
    for reason, count in sorted(reasons.items()):
        console.print(f"  dropped {count}: {reason}")
    console.print("next: [bold]data review[/bold], then [bold]data curate[/bold]")


@app.command("review")
def review_cmd(
    src: Path = typer.Option(None, help="Defaults to the verified set."),
    ledger_path: Path = typer.Option(None, "--ledger", help="Defaults to the committed ledger."),
    by: str = typer.Option("", help="Who is reviewing. Defaults to USER."),
    limit: int = typer.Option(0, help="Stop after this many. 0 is every one."),
) -> None:
    """Judge each unreviewed example: keep it, drop it, fix its reply, or skip it."""
    cfg = load()
    ledger_path = ledger_path or cfg.training.decisions_path
    try:
        examples = _read(src or cfg.training.verified_path)
    except TrainingError as exc:
        raise fail(exc) from exc
    ledger = curate.load(ledger_path)
    waiting = curate.pending(examples, ledger)
    if not waiting:
        console.print("[green]nothing to review[/green]")
        return
    if limit:
        waiting = waiting[:limit]
    judged = 0
    for index, example in enumerate(waiting, start=1):
        review.show(console, example, index, len(waiting))
        verdict = review.answer(console, console.input(f"{review.PROMPT}\n> "))
        if verdict == "quit":
            break
        if verdict == "skip":
            continue
        reason = console.input("why> ") if verdict in ("drop", "fix") else ""
        decision = curate.decide(example, verdict, reason, by or os.environ.get("USER", ""))
        if verdict == "fix":
            edited = review.edit(example.reply)
            if edited is None:
                console.print("[yellow]unchanged; judged nothing[/yellow]")
                continue
            decision.reply = edited
        ledger.record(decision)
        curate.save(ledger_path, ledger)
        judged += 1
    console.print(f"[green]{judged}[/green] judged -> {ledger_path}")
    console.print_json(data=ledger.counts())


@app.command("curate")
def curate_cmd(
    src: Path = typer.Option(None, help="Defaults to the verified set."),
    out: Path = typer.Option(None, help="Defaults under training.data_dir."),
    ledger_path: Path = typer.Option(None, "--ledger", help="Defaults to the committed ledger."),
) -> None:
    """Build the training set from the examples a reviewer accepted."""
    cfg = load()
    try:
        examples = _read(src or cfg.training.verified_path)
    except TrainingError as exc:
        raise fail(exc) from exc
    out = out or cfg.training.training_path
    ledger = curate.load(ledger_path or cfg.training.decisions_path)
    accepted, counts = curate.apply(examples, ledger)
    _write(out, accepted)
    console.print(f"[green]{len(accepted)}[/green] examples -> {out}")
    console.print_json(data=counts)
    if counts["unreviewed"]:
        console.print(f"[yellow]{counts['unreviewed']}[/yellow] unreviewed; run data review")
    if counts["stale"]:
        console.print(f"[yellow]{counts['stale']}[/yellow] changed since judged; review them again")


@app.command("stats")
def stats_cmd(src: Path = typer.Option(None, help="Defaults to the training set.")) -> None:
    """What the training set holds, and how much of the verified set has been judged."""
    cfg = load()
    try:
        examples = _read(src or cfg.training.training_path)
    except TrainingError as exc:
        raise fail(exc) from exc
    ledger = curate.load(cfg.training.decisions_path)
    verified = cfg.training.verified_path
    waiting = len(curate.pending(_read(verified), ledger)) if verified.exists() else 0
    console.print_json(
        json.dumps(
            {
                "examples": len(examples),
                "with_tool_calls": sum(1 for e in examples if e.tool_calls),
                "orgs": len({e.org_id for e in examples if e.org_id}),
                "platforms": sorted({e.platform for e in examples if e.platform}),
                "decisions": ledger.counts(),
                "unreviewed": waiting,
            }
        )
    )
