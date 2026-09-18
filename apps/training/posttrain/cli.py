"""train sft."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from training.core.types import TrainingError
from training.posttrain import sft

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()
err = Console(stderr=True)

DEFAULT_CONFIG = Path("apps/training/configs/train/sft.yaml")


@app.callback()
def main() -> None:
    """Post-training over the curated set."""


@app.command("sft")
def sft_cmd(
    config: Path = typer.Option(DEFAULT_CONFIG, help="The training config."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the plan and stop."),
) -> None:
    """Fine-tune on what a reviewer accepted."""
    try:
        drawn = sft.plan(config)
        console.print_json(data=drawn.model_dump(mode="json"))
        if dry_run:
            return
        adapter = sft.train(config)
    except TrainingError as exc:
        err.print("[red]error[/red] ", end="")
        err.print(str(exc), markup=False, highlight=False)
        raise typer.Exit(1) from exc
    console.print(f"[green]adapter[/green] -> {adapter}")
