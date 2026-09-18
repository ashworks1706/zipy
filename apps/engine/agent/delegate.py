"""The delegate tool: the same loop, once, on a subtask.

It is not a plugin. A plugin lives below the agent and cannot reach the orchestrator, and a
sub-agent is the orchestrator. So the schema is declared here and the call is answered by the
orchestrator itself rather than by the executor.

A sub-agent gets a task, a subset of the parent's tools, and its own turn limit. It is never
offered this tool, which is what keeps the request two levels deep.
"""

from __future__ import annotations

from typing import Any

from engine.core.types import ConfigError, ToolCall

#: The function name the model calls. It has no dot, so the registry never resolves it.
NAME = "delegate"

#: The depth a sub-agent runs at. The parent is 0.
SUB_AGENT_DEPTH = 1


def schema(tools: list[str]) -> dict[str, Any]:
    """The function-calling schema of delegation, naming the tools it may be given."""
    return {
        "type": "function",
        "function": {
            "name": NAME,
            "description": (
                "Hand one self-contained subtask to a fresh run of yourself, with only the tools "
                "you name. Use it when a subtask needs several lookups whose details you do not "
                "need, and you want the conclusion rather than every step. It cannot delegate "
                "again. Say everything it needs in the task: it cannot see this conversation."
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "task": {
                        "type": "string",
                        "description": (
                            "What to do, stated so it stands alone. Include every name, date and "
                            "identifier it needs."
                        ),
                    },
                    "tools": {
                        "type": "array",
                        "items": {"type": "string", "enum": tools},
                        "description": "The tools it may use. Give it the fewest that will do.",
                    },
                },
                "required": ["task", "tools"],
            },
        },
    }


def task_of(call: ToolCall) -> str:
    """The task a delegate call asks for. An empty task is a ConfigError."""
    task = str(call.arguments.get("task") or "").strip()
    if not task:
        raise ConfigError("delegate was called with no task")
    return task


def tools_of(call: ToolCall, offered: list[str]) -> list[str]:
    """The tools a sub-agent gets: what it asked for, kept to what the parent has.

    Asking for a tool the parent does not have is not an error. The sub-agent runs with the rest
    and says what it could not do, which is what every other narrowing here does.
    """
    asked = call.arguments.get("tools")
    wanted = [str(name) for name in asked] if isinstance(asked, list) else []
    return [name for name in offered if name in wanted]


def result(text: str, ran: list[str]) -> str:
    """What the parent reads back: the conclusion, and what was done to reach it."""
    done = ", ".join(ran) if ran else "no tools"
    return f"{text}\n\n[delegate ran: {done}]"
