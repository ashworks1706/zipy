"""Roles against action types."""

import pytest

from engine.auth.permissions import allowed, require
from engine.core.types import ActionType, PermissionDenied, Role


def test_a_member_reads_but_does_not_write(cfg):
    assert allowed(cfg.permissions, Role.MEMBER, ActionType.READ)
    with pytest.raises(PermissionDenied, match="calendar.create_event"):
        require(cfg.permissions, Role.MEMBER, ActionType.CREATE, "calendar.create_event")


def test_an_org_may_let_members_create(cfg):
    overrides = {Role.MEMBER: frozenset({ActionType.READ, ActionType.CREATE})}
    assert allowed(cfg.permissions, Role.MEMBER, ActionType.CREATE, overrides)
