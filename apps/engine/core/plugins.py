"""Discovery shared by every plugin kind: platforms, providers and tools.

A plugin is a subpackage of its kind's package holding one module that defines a subclass of the
kind's base class. Each plugin has a name, which is also the name of its table in zipy.toml, and
declares the third-party libraries it owns; no other engine module imports them.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from collections.abc import Mapping
from typing import Any, ClassVar, Protocol

from engine.core.types.errors import ConfigError


class Plugin(Protocol):
    """What every plugin class declares."""

    name: ClassVar[str]
    owns: ClassVar[tuple[str, ...]]


def discover(package: str, module: str, base: type[Any]) -> dict[str, type[Any]]:
    """Every subclass of base defined in package.<plugin>.<module>, by plugin name."""
    root = importlib.import_module(package)
    found: dict[str, type[Any]] = {}
    for info in pkgutil.iter_modules(root.__path__):
        if not info.ispkg:
            continue
        loaded = importlib.import_module(f"{package}.{info.name}.{module}")
        for _, member in inspect.getmembers(loaded, inspect.isclass):
            if (
                issubclass(member, base)
                and member is not base
                and member.__module__ == loaded.__name__
            ):
                name = str(getattr(member, "name", ""))
                if name != info.name:
                    raise ConfigError(
                        f"{member.__qualname__}.name must be its folder name, {info.name}"
                    )
                if name in found:
                    raise ConfigError(f"{package}.{name} defines two plugin classes")
                found[name] = member
    return found


def match(kind: str, classes: Mapping[str, object], tables: Mapping[str, object]) -> None:
    """Fail unless every plugin has a [kind.name] table and every table has a plugin."""
    differ = sorted(set(classes) ^ set(tables))
    if differ:
        raise ConfigError(f"{kind} plugins and [{kind}.*] tables differ: {differ}")
