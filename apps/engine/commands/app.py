"""zipy serve, chat, eval, eval-add, traces, config, plugins and db."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from engine.core.config import load
from engine.core.types import ZipyError
from engine.tools.registry import Registry

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()
err = Console(stderr=True)

MIGRATIONS = Path(__file__).resolve().parent.parent / "data" / "migrations"

#: The repository's evals folder, three levels above apps/engine/commands.
EVALS = Path(__file__).resolve().parents[3] / "evals"


def fail(exc: ZipyError) -> typer.Exit:
    """Print an error without a traceback and exit 1."""
    # The message is data: a config error names tables like [platforms.*], which are not markup.
    err.print("[red]error[/red] ", end="")
    err.print(str(exc), markup=False, highlight=False)
    return typer.Exit(1)


@app.command()
def serve() -> None:
    """Run every enabled platform, the HTTP server and the workers."""
    from engine.wiring import serve as run

    try:
        asyncio.run(run(load()))
    except ZipyError as exc:
        raise fail(exc) from exc


@app.command()
def chat(
    jsonl: bool = typer.Option(False, help="speak JSON lines, as the console does"),
) -> None:
    """Talk to Zipy in this terminal through the local platform, with no chat app."""
    import os

    from engine.wiring import serve as run

    os.environ["ZIPY_PLATFORMS__LOCAL__JSONL"] = "true" if jsonl else "false"
    load.cache_clear()
    try:
        asyncio.run(run(load(), only=("local",)))
    except ZipyError as exc:
        raise fail(exc) from exc


@app.command("eval")
def run_eval(
    directory: Path = typer.Option(EVALS, help="where cases.toml and fixtures.toml live"),
    case: str = typer.Option("", help="run one case by its id"),
) -> None:
    """Run the eval cases against the configured model, over fixtures rather than providers."""
    from engine.evals import report, runner
    from engine.evals.cases import load as load_cases
    from engine.evals.fixtures import load as load_fixtures
    from engine.evals.stack import build

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


@app.command("eval-add")
def eval_add(
    request_id: str = typer.Argument(..., help="the request whose trace becomes a case"),
    case_id: str = typer.Option(..., "--id", help="the id the case is known by"),
    directory: Path = typer.Option(EVALS, help="where cases.toml lives"),
) -> None:
    """Draft an eval case from a real request and append it to the cases.

    The draft records what the request did. What it should have carried is for the reviewer to
    fill in, which is what contains is left empty for.
    """
    from engine.evals import draft as drafting
    from engine.evals.cases import load as load_cases

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


@app.command()
def traces(
    request_id: str = typer.Argument("", help="print one request's events"),
    limit: int = typer.Option(20, help="how many requests to list"),
) -> None:
    """The newest requests under telemetry.trace_dir, or one request's events in order."""
    try:
        directory = Path(load().telemetry.trace_dir)
    except ZipyError as exc:
        raise fail(exc) from exc
    files = sorted(directory.glob("*/*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
    if request_id:
        found = [f for f in files if f.stem == request_id]
        if not found:
            raise fail(ZipyError(f"no trace for request {request_id} under {directory}"))
        for line in found[0].read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            console.print(f"[dim]{event['at']}[/dim] [bold]{event['event']}[/bold]", event["data"])
        return
    grid = Table("request", "org", "platform", "events", "last event", "at")
    for path in files[:limit]:
        lines = path.read_text(encoding="utf-8").splitlines()
        if not lines:
            continue
        last = json.loads(lines[-1])
        grid.add_row(
            path.stem,
            path.parent.name,
            last["platform"],
            str(len(lines)),
            last["event"],
            last["at"][:19],
        )
    console.print(grid)


@app.command()
def config(table: str = typer.Argument("", help="one table, such as agent or tools")) -> None:
    """Print the resolved configuration, secrets masked."""
    try:
        data = load().redacted()
    except ZipyError as exc:
        raise fail(exc) from exc
    if table and table not in data:
        raise fail(ZipyError(f"no table {table}"))
    console.print_json(data=data[table] if table else data)


@app.command()
def plugins() -> None:
    """Check every platform, provider and tool plugin against zipy.toml and list them."""
    from engine.auth.providers.registry import Providers
    from engine.platforms.registry import check, platform_classes

    try:
        cfg = load()
        classes = platform_classes()
        check(cfg.platforms, classes)
        providers = Providers(cfg.providers, cfg.api.public_url)
        registry = Registry(cfg.tools)
    except ZipyError as exc:
        raise fail(exc) from exc
    grid = Table("kind", "name", "enabled", "needs", "actions")
    for name in sorted(classes):
        grid.add_row("platform", name, str(cfg.platforms[name].enabled), "", "")
    for name in sorted(providers.classes):
        grid.add_row("provider", name, str(cfg.providers[name].enabled), "", "")
    for name in registry.names:
        table = cfg.tools[name]
        actions = ", ".join(f"{a} ({k.value})" for a, k in table.actions.items())
        grid.add_row("tool", name, str(table.enabled), table.provider, actions)
    console.print(grid)


@app.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def db(ctx: typer.Context) -> None:
    """Run alembic against the engine database: upgrade head, revision MESSAGE, downgrade -1."""
    from alembic import command
    from alembic.config import Config as AlembicConfig

    args = list(ctx.args) or ["upgrade", "head"]
    alembic = AlembicConfig()
    alembic.set_main_option("script_location", str(MIGRATIONS))
    verb, rest = args[0], args[1:]
    if verb == "upgrade":
        command.upgrade(alembic, rest[0] if rest else "head")
    elif verb == "downgrade":
        command.downgrade(alembic, rest[0] if rest else "-1")
    elif verb == "revision" and rest:
        command.revision(alembic, message=" ".join(rest), autogenerate=True)
    elif verb == "current":
        command.current(alembic)
    else:
        raise fail(ZipyError("db takes upgrade [rev], downgrade [rev], revision MESSAGE, current"))
