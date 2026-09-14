"""The signed OAuth state parameter: which org and admin started a connect, and when."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pydantic import SecretStr

from engine.core.types import MemberRef, OrgId


@dataclass(frozen=True)
class ConnectState:
    """Who is connecting which provider for which org."""

    org_id: OrgId
    member: MemberRef
    provider: str
    issued_at: datetime


def sign(state: ConnectState, key: SecretStr) -> str:
    """The state as an opaque, tamper-evident string for the authorize URL."""
    raise NotImplementedError


def verify(token: str, key: SecretStr, now: datetime, max_age_secs: int) -> ConnectState:
    """The state a token holds. A bad signature or an old token is an OAuthError."""
    raise NotImplementedError
