"""The signed OAuth state parameter: which org and admin started a connect, and when."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import SecretStr

from engine.core.types import ConfigError, MemberRef, OAuthError, OrgId

# The payload shape the signature covers. A token of another version does not verify.
STATE_VERSION = 1

# The shortest signing key accepted, in characters.
MIN_KEY_CHARS = 32

# How far ahead of now a token may claim to have been issued, in seconds.
CLOCK_SKEW_SECS = 60

# Bytes of randomness that make two states for the same org, member and second differ.
NONCE_BYTES = 16


@dataclass(frozen=True)
class ConnectState:
    """Who is connecting which provider for which org."""

    org_id: OrgId
    member: MemberRef
    provider: str
    issued_at: datetime


def sign(state: ConnectState, key: SecretStr) -> str:
    """The state as an opaque, tamper-evident string for the authorize URL."""
    if state.issued_at.tzinfo is None:
        raise OAuthError("oauth state issued_at has no timezone")
    payload = {
        "v": STATE_VERSION,
        "org": str(state.org_id),
        "platform": state.member.platform,
        "user": state.member.user_id,
        "provider": state.provider,
        "issued_at": state.issued_at.isoformat(),
        "nonce": _encode(secrets.token_bytes(NONCE_BYTES)),
    }
    body = _encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    return f"{body}.{_encode(_mac(body, key))}"


def verify(token: str, key: SecretStr, now: datetime, max_age_secs: int) -> ConnectState:
    """The state a token holds. A bad signature or an old token is an OAuthError."""
    if max_age_secs <= 0:
        raise ConfigError("the oauth state max age must be positive")
    if now.tzinfo is None:
        raise OAuthError("oauth state is verified against a time without a timezone")
    body, _, signature = token.partition(".")
    if not body or not signature or "." in signature:
        raise OAuthError("oauth state is not a signed token")
    if not hmac.compare_digest(_decode(signature), _mac(body, key)):
        raise OAuthError("oauth state signature does not verify")
    payload = _payload(body)
    issued_at = _issued_at(payload)
    age = (now - issued_at).total_seconds()
    if age > max_age_secs:
        raise OAuthError("oauth state has expired")
    if age < -CLOCK_SKEW_SECS:
        raise OAuthError("oauth state was issued in the future")
    return ConnectState(
        org_id=OrgId(_text(payload, "org")),
        member=MemberRef(_text(payload, "platform"), _text(payload, "user")),
        provider=_text(payload, "provider"),
        issued_at=issued_at,
    )


def _mac(body: str, key: SecretStr) -> bytes:
    secret = key.get_secret_value()
    if len(secret) < MIN_KEY_CHARS:
        raise ConfigError(
            f"the oauth state signing key is missing or shorter than {MIN_KEY_CHARS} characters"
        )
    return hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode())
    except (binascii.Error, ValueError) as exc:
        raise OAuthError("oauth state is not base64url") from exc


def _payload(body: str) -> dict[str, Any]:
    try:
        payload = json.loads(_decode(body))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OAuthError("oauth state payload is not readable") from exc
    if not isinstance(payload, dict):
        raise OAuthError("oauth state payload is not an object")
    if payload.get("v") != STATE_VERSION:
        raise OAuthError(f"oauth state is not version {STATE_VERSION}")
    return payload


def _text(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise OAuthError(f"oauth state has no {field}")
    return value


def _issued_at(payload: dict[str, Any]) -> datetime:
    try:
        issued_at = datetime.fromisoformat(_text(payload, "issued_at"))
    except ValueError as exc:
        raise OAuthError("oauth state issued_at is not a timestamp") from exc
    if issued_at.tzinfo is None:
        raise OAuthError("oauth state issued_at has no timezone")
    return issued_at
