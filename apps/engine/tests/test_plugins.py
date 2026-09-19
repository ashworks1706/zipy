"""Every plugin kind is discovered, matched to zipy.toml, and isolated from its siblings.

These rules replace per-plugin import contracts: a new plugin folder is covered without editing
pyproject.toml.
"""

from typing import Any

import grimp
import pytest

from engine.auth.providers.base import BaseProvider
from engine.auth.providers.registry import Providers
from engine.core.plugins import discover
from engine.platforms.base import BasePlatform
from engine.platforms.registry import check, platform_classes
from engine.tools.base import BaseTool

KINDS: list[tuple[str, str, type[Any]]] = [
    ("engine.platforms", "platform", BasePlatform),
    ("engine.auth.providers", "provider", BaseProvider),
    ("engine.tools", "tool", BaseTool),
]


@pytest.fixture(scope="module")
def graph() -> grimp.ImportGraph:
    return grimp.build_graph("engine", include_external_packages=True)


def test_every_plugin_kind_is_discovered():
    names = {package: set(discover(package, module, base)) for package, module, base in KINDS}
    assert names == {
        "engine.platforms": {"discord", "local", "slack"},
        "engine.auth.providers": {"github", "google", "notion", "zoom"},
        "engine.tools": {
            "calendar",
            "drive",
            "github",
            "gmail",
            "notion",
            "sandbox",
            "search",
            "workspace",
            "zoom",
        },
    }


def test_platforms_and_providers_match_the_committed_config(cfg):
    check(cfg.platforms, platform_classes())
    assert Providers(cfg.providers, cfg.api.public_url).enabled == [
        "github",
        "google",
        "notion",
        "zoom",
    ]


def test_every_tool_provider_is_a_provider_plugin():
    providers = set(discover("engine.auth.providers", "provider", BaseProvider))
    for tool in discover("engine.tools", "tool", BaseTool).values():
        assert not tool.provider or tool.provider in providers, tool.name


@pytest.mark.parametrize(("package", "module", "base"), KINDS)
def test_no_plugin_imports_a_sibling_plugin(graph, package, module, base):
    plugins = discover(package, module, base)
    for name in plugins:
        for other in plugins:
            if other != name:
                chains = graph.find_shortest_chains(
                    f"{package}.{name}", f"{package}.{other}", as_packages=True
                )
                assert not chains, f"{name} imports {other}: {chains}"


def test_an_owned_library_is_imported_only_by_its_owners(graph):
    owners: dict[str, set[str]] = {}
    for package, module, base in KINDS:
        for name, cls in discover(package, module, base).items():
            for library in cls.owns:
                owners.setdefault(library, set()).add(f"{package}.{name}")
    for library, allowed in owners.items():
        if library not in graph.modules:
            continue
        for importer in graph.find_modules_that_directly_import(library):
            assert any(importer == a or importer.startswith(a + ".") for a in allowed), (
                f"{importer} imports {library}, owned by {sorted(allowed)}"
            )
