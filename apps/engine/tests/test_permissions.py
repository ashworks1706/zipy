"""Roles against action types, and what a person's collaboration state may never move."""

import inspect
from pathlib import Path

import pytest

import engine.agent.classifier
import engine.auth.permissions
from engine.agent.classifier import needs_confirmation
from engine.auth.permissions import allowed, require
from engine.core.types import ActionType, MemberRef, PermissionDenied, Role, ToolCall
from engine.core.types.collaboration import (
    CollaborationState,
    Dimension,
    Evidence,
    Signal,
    apply_signals,
)
from engine.tools.registry import Registry


def test_a_member_reads_but_does_not_write(cfg):
    assert allowed(cfg.permissions, Role.MEMBER, ActionType.READ)
    with pytest.raises(PermissionDenied, match="calendar.create_event"):
        require(cfg.permissions, Role.MEMBER, ActionType.CREATE, "calendar.create_event")


def test_an_org_may_let_members_create(cfg):
    overrides = {Role.MEMBER: frozenset({ActionType.READ, ActionType.CREATE})}
    assert allowed(cfg.permissions, Role.MEMBER, ActionType.CREATE, overrides)


def test_collaboration_state_cannot_relax_a_confirmation(cfg):
    """The VISION invariant: adaptation moves tone and autonomy, never the confirmation bar."""
    member = MemberRef(platform="discord", user_id="u1")
    maximal = apply_signals(
        CollaborationState(member=member),
        [Signal(Dimension.AUTONOMY, target=1.0, evidence=Evidence.STATED_PREFERENCE, weight=1e6)],
    )
    assert maximal.score(Dimension.AUTONOMY) == pytest.approx(1.0)

    registry = Registry(cfg.tools)
    call = ToolCall(id="c1", name="calendar.delete_event", arguments={"event_id": "e1"})
    assert needs_confirmation(registry, call)

    assert "collaboration" not in inspect.signature(needs_confirmation).parameters
    assert "collaboration" not in inspect.signature(allowed).parameters
    assert "collaboration" not in inspect.signature(require).parameters


def test_nothing_that_decides_a_permission_imports_collaboration():
    """Held statically, so wiring the two together fails here rather than in review."""
    for module in (engine.agent.classifier, engine.auth.permissions):
        source = Path(inspect.getfile(module)).read_text()
        assert "collaboration" not in source, module.__name__
