"""The tool registry holds every tool plugin to zipy.toml."""

from datetime import UTC, datetime

import pytest

from engine.agent.classifier import needs_confirmation
from engine.core.config import ToolSettings
from engine.core.types import ActionType, ConfigError, OrgToolConfig, ToolCall, wire_name
from engine.tools.registry import Registry


def test_the_committed_config_matches_every_tool(cfg):
    assert Registry(cfg.tools).names == [
        "calendar",
        "drive",
        "github",
        "gmail",
        "notion",
        "search",
        "workspace",
        "zoom",
    ]


def test_a_table_without_a_plugin_fails_at_startup(cfg):
    tables = dict(cfg.tools)
    tables["trello"] = ToolSettings(actions={"list": ActionType.READ})
    with pytest.raises(ConfigError, match="trello"):
        Registry(tables)


def test_an_action_missing_from_the_config_fails_at_startup(cfg):
    tables = dict(cfg.tools)
    actions = dict(tables["calendar"].actions)
    del actions["delete_event"]
    tables["calendar"] = tables["calendar"].model_copy(update={"actions": actions})
    with pytest.raises(ConfigError, match="delete_event"):
        Registry(tables)


def test_only_connected_and_enabled_tools_are_offered(cfg):
    registry = Registry(cfg.tools)
    assert registry.available(frozenset(), {}) == ["search"]
    assert registry.available(frozenset({"google"}), {}) == [
        "calendar",
        "drive",
        "gmail",
        "search",
        "workspace",
    ]
    off = {"drive": OrgToolConfig("drive", enabled=False, overrides={})}
    assert "drive" not in registry.available(frozenset({"google"}), off)


def test_an_org_that_turns_a_tool_off_is_not_offered_it(cfg):
    """The file says on; an org override is what decides for that org."""
    registry = Registry(cfg.tools)
    off = {"zoom": OrgToolConfig("zoom", enabled=False, overrides={})}
    assert "zoom" in registry.available(frozenset({"zoom"}), {})
    assert "zoom" not in registry.available(frozenset({"zoom"}), off)


def test_a_tool_whose_provider_is_not_connected_is_not_offered(cfg):
    registry = Registry(cfg.tools)
    assert "github" not in registry.available(frozenset(), {})
    assert "github" in registry.available(frozenset({"github"}), {})
    # search needs no account, so it is there either way.
    assert "search" in registry.available(frozenset(), {})


def test_an_org_override_is_merged_over_the_file(cfg):
    registry = Registry(cfg.tools)
    override = OrgToolConfig("calendar", enabled=True, overrides={"max_result_chars": 500})
    settings = registry.settings_for("calendar", override)
    assert settings.model_dump()["max_result_chars"] == 500
    assert settings.model_dump()["endpoint"] == cfg.tools["calendar"].options["endpoint"]


def test_an_unknown_override_key_is_rejected(cfg):
    registry = Registry(cfg.tools)
    override = OrgToolConfig("calendar", enabled=True, overrides={"reminder": 15})
    with pytest.raises(ConfigError):
        registry.settings_for("calendar", override)


def test_syncing_tools_are_the_ones_that_produce_documents(cfg):
    assert Registry(cfg.tools).syncing() == ["drive", "notion", "zoom"]


def test_function_names_round_trip_without_dots(cfg):
    registry = Registry(cfg.tools)
    names = [s["function"]["name"] for s in registry.schemas(["calendar"])]
    assert wire_name("calendar.create_event") in names
    assert all("." not in n for n in names)
    assert registry.resolve("calendar__create_event") == ("calendar", "create_event")


def test_the_config_not_the_model_decides_what_needs_confirmation(cfg):
    registry = Registry(cfg.tools)
    at = datetime(2026, 9, 13, tzinfo=UTC).isoformat()
    assert not needs_confirmation(registry, ToolCall("1", "calendar.create_event", {"start": at}))
    assert needs_confirmation(registry, ToolCall("2", "calendar.update_event", {}))
    with pytest.raises(ConfigError):
        needs_confirmation(registry, ToolCall("3", "calendar.drop_everything", {}))
