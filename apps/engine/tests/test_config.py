"""zipy.toml loads, and bad combinations are rejected at load."""

import pytest

from engine.core.config import CONFIG_VERSION, Config
from engine.core.types import ActionType, ConfigError, Role


def test_the_committed_config_loads(cfg):
    assert cfg.config_version == CONFIG_VERSION
    assert cfg.agent.max_iterations == 8
    assert cfg.tools["calendar"].actions["delete_event"] is ActionType.DESTRUCTIVE
    assert set(cfg.models) == {"chat", "summary", "embedding"}


def test_members_only_read_by_default(cfg):
    assert cfg.permissions.allowed(Role.MEMBER) == {ActionType.READ}


def test_an_env_var_wins_over_the_file(cfg, monkeypatch):
    monkeypatch.setenv("ZIPY_AGENT__MAX_ITERATIONS", "3")
    monkeypatch.setenv("ZIPY_MODELS__CHAT__MODEL", "anthropic/claude-haiku-4-5")
    loaded = Config(_env_file=None)
    assert loaded.agent.max_iterations == 3
    assert loaded.models["chat"].model == "anthropic/claude-haiku-4-5"


def test_a_plugin_secret_from_the_env_reaches_its_table_and_is_masked(cfg, monkeypatch):
    monkeypatch.setenv("ZIPY_PLATFORMS__DISCORD__TOKEN", "abc")
    loaded = Config(_env_file=None)
    assert loaded.platforms["discord"].options["token"] == "abc"
    assert loaded.redacted()["platforms"]["discord"]["token"] == "**********"
    assert "abc" not in str(loaded.redacted())


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("ZIPY_CONFIG_VERSION", "0", "config_version"),
        ("ZIPY_MEMORY__CHUNK_OVERLAP_TOKENS", "500", "chunk_overlap_tokens"),
        ("ZIPY_PLATFORMS__DISCORD__ENABLED", "false", "no \\[platforms"),
        ("ZIPY_TOOLS__CALENDAR__PROVIDER", "outlook", "outlook"),
    ],
)
def test_a_bad_combination_is_rejected_at_load(cfg, monkeypatch, key, value, message):
    monkeypatch.setenv(key, value)
    with pytest.raises((ConfigError, ValueError), match=message):
        Config(_env_file=None)
