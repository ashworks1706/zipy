"""evals run and evals add."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import typer
from rich.console import Console

from engine.core.config import load
from engine.core.types import ZipyError
from testbed.evals import draft as drafting
from testbed.evals import report, runner
from testbed.evals.cases import load as load_cases
from testbed.evals.fixtures import load as load_fixtures
from testbed.evals.stack import build

app = typer.Typer(no_args_is_help=True, add_completion=False, help="The eval cases.")
console = Console()
err = Console(stderr=True)

#: The repository's evals folder, three levels above apps/testbed/evals.
EVALS = Path(__file__).resolve().parents[3] / "evals"


def fail(exc: ZipyError) -> typer.Exit:
    """Print an error without a traceback and exit 1."""
    err.print(f"[red]{type(exc).__name__}[/red] {exc}")
    return typer.Exit(1)


@app.command("run")
def run_eval(
    directory: Path = typer.Option(EVALS, help="where cases.toml and fixtures.toml live"),
    case: str = typer.Option("", help="run one case by its id"),
) -> None:
    """Run the eval cases against the configured model, over fixtures rather than providers."""
    try:
        suite = load_cases(directory / "cases.toml")
        raw = load_fixtures(directory / "fixtures.toml")
        if case:
            if case not in suite.by_id:
                raise ZipyError(f"no case {case} in {directory / 'cases.toml'}")
            suite = replace(suite, cases=(suite.by_id[case],), contrasts=())
        stack = build(load(), raw)
        runs, pairs = asyncio.run(runner.run(stack, suite))
    except ZipyError as exc:
        raise fail(exc) from exc
    report.render(console, runs, pairs)
    if not all(run.correctness.passed for run in runs):
        raise typer.Exit(1)


@app.command("add")
def eval_add(
    request_id: str = typer.Argument(..., help="the request whose trace becomes a case"),
    case_id: str = typer.Option(..., "--id", help="the id the case is known by"),
    directory: Path = typer.Option(EVALS, help="where cases.toml lives"),
) -> None:
    """Draft an eval case from a real request and append it to the cases.

    The draft records what the request did. What it should have carried is for the reviewer to
    fill in, which is what contains is left empty for.
    """
    cfg = load()
    cases = directory / "cases.toml"
    try:
        suite = load_cases(cases) if cases.exists() else None
        if suite is not None and case_id in suite.by_id:
            raise ZipyError(f"{cases} already holds a case called {case_id}")
        path = drafting.find(Path(cfg.telemetry.trace_dir), request_id)
        case = drafting.draft(case_id, drafting.events(path))
    except ZipyError as exc:
        raise fail(exc) from exc
    with cases.open("a", encoding="utf-8") as handle:
        handle.write("\n" + drafting.as_toml(case))
    console.print(f"[green]{case.id}[/green] -> {cases}")
    console.print("fill in contains, then run it with [bold]just eval[/bold]")
