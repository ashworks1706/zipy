"""The eval cases, as they are written in evals/cases.toml.

A case names a story in docs/USER_STORIES.md by its id, the message that opens it, and what a run
is scored against. A contrast names a case to run twice under two collaboration states, which is
how the behaviour axis is read.
"""

from __future__ import annotations

import tomllib
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engine.core.types import ConfigError, Dimension


@dataclass(frozen=True)
class Case:
    """One message and what the run must get right."""

    #: The id of the story in docs/USER_STORIES.md.
    id: str
    ask: str
    #: The qualified tool actions the run must make, in any order.
    calls: tuple[str, ...] = ()
    #: Text the answer must carry, matched without case.
    contains: tuple[str, ...] = ()
    #: Whether the run must stop for a confirmation before anything changes.
    confirms: bool = False
    #: The answer to give a confirmation the run asks for.
    approve: bool = True


@dataclass(frozen=True)
class Contrast:
    """One case run at both ends of one dimension."""

    case: str
    dimension: Dimension


@dataclass(frozen=True)
class Suite:
    """Every case and contrast one file holds."""

    cases: tuple[Case, ...] = ()
    contrasts: tuple[Contrast, ...] = ()
    by_id: dict[str, Case] = field(default_factory=dict)


def _strings(raw: dict[str, Any], key: str) -> tuple[str, ...]:
    """One list of strings from a case table, empty when it names none."""
    values = raw.get(key, ())
    if isinstance(values, str) or not isinstance(values, Sequence):
        raise ConfigError(f"{key} in a case is a list of strings")
    return tuple(str(value) for value in values)


def _case(raw: dict[str, Any], where: Path) -> Case:
    """One [[case]] table, or a ConfigError naming what is wrong with it."""
    missing = [key for key in ("id", "ask") if key not in raw]
    if missing:
        raise ConfigError(f"a case in {where} has no {' and no '.join(missing)}")
    return Case(
        id=str(raw["id"]),
        ask=str(raw["ask"]),
        calls=_strings(raw, "calls"),
        contains=_strings(raw, "contains"),
        confirms=bool(raw.get("confirms", False)),
        approve=bool(raw.get("approve", True)),
    )


def _contrast(raw: dict[str, Any], where: Path, known: set[str]) -> Contrast:
    """One [[contrast]] table, or a ConfigError naming what is wrong with it."""
    case, dimension = str(raw.get("case", "")), str(raw.get("dimension", ""))
    if case not in known:
        raise ConfigError(f"a contrast in {where} names no case: {case or 'nothing'}")
    if dimension not in tuple(Dimension):
        raise ConfigError(f"contrast {case} names no dimension: {dimension or 'nothing'}")
    return Contrast(case=case, dimension=Dimension(dimension))


def load(path: Path) -> Suite:
    """Every case and contrast in one file. A duplicate id is a ConfigError."""
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    cases = tuple(_case(entry, path) for entry in raw.get("case", ()))
    by_id: dict[str, Case] = {}
    for case in cases:
        if case.id in by_id:
            raise ConfigError(f"{path} holds case {case.id} twice")
        by_id[case.id] = case
    contrasts = tuple(_contrast(entry, path, set(by_id)) for entry in raw.get("contrast", ()))
    return Suite(cases=cases, contrasts=contrasts, by_id=by_id)
