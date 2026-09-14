"""The catalog of everything the console runs, in sidebar order, and its command line.

Every unit is a just recipe line. Most units are tasks, run when asked. The agent is zipy chat
through the local platform: it starts with the console and speaks JSON lines to the chat pane. A
service unit is one compose service: it shows whether the service is up, starting or stopping it
runs just up or just stop, and its logs are followed for as long as it runs.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class Group(StrEnum):
    """A sidebar section."""

    SERVICES = "services"
    SETUP = "setup"
    GATE = "gate"
    ENGINE = "engine"
    INSPECT = "inspect"
    WEBSITE = "website"
    DEPLOY = "deploy"
    ADHOC = "ad-hoc"


class Kind(StrEnum):
    """How the console runs a unit."""

    TASK = "task"
    AGENT = "agent"
    SERVICE = "service"


@dataclass(frozen=True)
class Unit:
    """One just recipe line. Its id is the line itself; name is what the sidebar shows."""

    group: Group
    args: tuple[str, ...]
    hint: str
    kind: Kind = Kind.TASK
    label: str = ""
    # The compose service a service unit starts, stops and follows.
    service: str = ""

    @property
    def id(self) -> str:
        return " ".join(self.args)

    @property
    def name(self) -> str:
        return self.label or self.id


def _unit(
    group: Group, line: str, hint: str, kind: Kind = Kind.TASK, label: str = "", service: str = ""
) -> Unit:
    return Unit(group, tuple(line.split()), hint, kind, label, service)


def adhoc(args: Sequence[str]) -> Unit:
    """A recipe typed at the command line."""
    return Unit(Group.ADHOC, tuple(args), "typed at the command line")


# The compose services: name in deploy/compose.yml, and what it is for.
SERVICES = (
    ("postgres", "orgs, workspaces, credentials, context, documents, audit"),
    ("redis", "rate limits and the job queue"),
    ("langfuse", "model and tool traces, at :3000"),
    ("prometheus", "the metrics history the dashboards read, at :9090"),
    ("grafana", "dashboards over prometheus, at :3002"),
    ("uptime-kuma", "uptime checks and alerts, at :3001"),
)


def catalog() -> list[Unit]:
    """Every unit the console lists."""
    units = [
        _unit(Group.SERVICES, "chat --jsonl", "chat with Zipy on the right", Kind.AGENT, "zipy"),
    ]
    units += [
        _unit(Group.SERVICES, f"logs {service}", hint, Kind.SERVICE, service, service)
        for service, hint in SERVICES
    ]
    units.append(_unit(Group.SERVICES, "down", "stop and remove every compose service"))
    units += [
        _unit(Group.SETUP, "doctor", "tools, secrets, services"),
        _unit(Group.SETUP, "setup", "install every app"),
        _unit(Group.SETUP, "migrate", "apply database migrations"),
        _unit(Group.GATE, "check", "the Python apps and the website"),
        _unit(Group.GATE, "check-python", "format, lint, layering, types, tests"),
        _unit(Group.GATE, "fmt", "format in place"),
        _unit(Group.GATE, "test integration", "tests against postgres and redis"),
        _unit(Group.GATE, "diagrams", "render every mermaid diagram in the docs"),
        _unit(Group.ENGINE, "serve", "every enabled platform, the HTTP server, the workers"),
        _unit(Group.INSPECT, "plugins", "platforms, providers and tools against zipy.toml"),
        _unit(Group.INSPECT, "traces", "the newest request traces"),
        _unit(Group.INSPECT, "config", "the resolved configuration, secrets masked"),
        _unit(Group.WEBSITE, "web", "the website's dev server at :3000"),
        _unit(Group.WEBSITE, "check-website", "eslint and tsc over the website"),
        _unit(Group.WEBSITE, "web-build", "the website's production build"),
        _unit(Group.WEBSITE, "web-frames", "regenerate the website's logo animation"),
        _unit(Group.DEPLOY, "image", "build the zipy image"),
    ]
    return units


Verb = Literal["quit", "help", "clear", "start", "stop", "restart", "just", "none"]


@dataclass(frozen=True)
class Command:
    """A parsed command line. arg names the unit for start, stop and restart."""

    verb: Verb
    arg: str = ""
    args: tuple[str, ...] = ()


def parse_command(text: str) -> Command:
    """The command typed after a colon. Anything unrecognised runs as a just recipe."""
    words = text.split()
    if not words:
        return Command("none")
    head, rest = words[0], words[1:]
    arg = " ".join(rest)
    if head in ("q", "quit"):
        return Command("quit")
    if head in ("h", "help"):
        return Command("help")
    if head == "clear":
        return Command("clear")
    if head == "start" and arg:
        return Command("start", arg=arg)
    if head == "stop" and arg:
        return Command("stop", arg=arg)
    if head == "restart" and arg:
        return Command("restart", arg=arg)
    if head == "just":
        return Command("just", args=tuple(rest))
    return Command("just", args=tuple(words))
