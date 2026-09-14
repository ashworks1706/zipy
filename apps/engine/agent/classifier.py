"""Whether a tool call runs at once or waits for a click. zipy.toml decides, never the model."""

from __future__ import annotations

from engine.core.types import ActionType, ToolCall
from engine.tools.registry import Registry


def classify(registry: Registry, call: ToolCall) -> ActionType:
    """The action type of a call. An unknown action is a ConfigError."""
    return registry.action_type(call.name)


def needs_confirmation(registry: Registry, call: ToolCall) -> bool:
    """True for destructive calls."""
    return classify(registry, call) is ActionType.DESTRUCTIVE
