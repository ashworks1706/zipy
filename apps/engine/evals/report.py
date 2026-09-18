"""The two tables a run prints, one per axis."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from engine.evals.runner import Pair, Run


def _mark(ok: bool) -> str:
    """A passed or failed cell."""
    return "[green]pass[/green]" if ok else "[red]fail[/red]"


def correctness_table(runs: list[Run]) -> Table:
    """One row per case: what it called, and which checks it failed."""
    grid = Table("case", "result", "calls", "failed", title="Correctness")
    for run in sorted(runs, key=lambda r: r.case):
        failed = run.error or ", ".join(run.correctness.failures())
        grid.add_row(run.case, _mark(run.correctness.passed), ", ".join(run.calls), failed)
    return grid


def behaviour_table(runs: list[Run]) -> Table:
    """One row per case: how it answered, measured rather than judged."""
    grid = Table("case", "words", "asked", "first call", "calls", title="Behaviour")
    for run in sorted(runs, key=lambda r: r.case):
        grid.add_row(
            run.case,
            str(run.behaviour.words),
            "yes" if run.behaviour.asked else "no",
            run.behaviour.first_call,
            str(run.behaviour.calls),
        )
    return grid


def contrast_table(pairs: list[Pair]) -> Table:
    """One row per contrast: correctness must hold, behaviour must move."""
    columns = ("case", "dimension", "correctness held", "behaviour moved", "words")
    grid = Table(*columns, title="Contrast")
    for pair in pairs:
        grid.add_row(
            pair.case,
            pair.dimension.value,
            _mark(pair.held),
            _mark(pair.moved),
            f"{pair.low.behaviour.words} to {pair.high.behaviour.words}",
        )
    return grid


def summary(runs: list[Run], pairs: list[Pair]) -> str:
    """One line: how many cases passed, and how many contrasts did what they are for."""
    passed = sum(1 for run in runs if run.correctness.passed)
    line = f"{passed} of {len(runs)} cases correct"
    if pairs:
        worked = sum(1 for pair in pairs if pair.held and pair.moved)
        line = f"{line}; {worked} of {len(pairs)} contrasts held correctness and moved behaviour"
    return line


def render(console: Console, runs: list[Run], pairs: list[Pair]) -> None:
    """Every table, then the summary line."""
    console.print(correctness_table(runs))
    console.print(behaviour_table(runs))
    if pairs:
        console.print(contrast_table(pairs))
    console.print(summary(runs, pairs))
