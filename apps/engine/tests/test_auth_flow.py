"""The signed OAuth state, the provider plugins, and the callback that stores a credential."""

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import ClassVar

import httpx
import pytest
import structlog
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, SecretStr

from engine.api.routes.oauth import OAuthRoutes
from engine.auth.providers.base import BaseProvider
from engine.auth.providers.google import provider as google_module
from engine.auth.providers.google.provider import GoogleProvider, GoogleSettings
from engine.auth.providers.notion.provider import NotionProvider, NotionSettings
from engine.auth.providers.registry import Providers
from engine.auth.providers.zoom.provider import ZoomProvider, ZoomSettings
from engine.auth.state import ConnectState, _mac, sign, verify
from engine.core.config import ProviderSettings
from engine.core.doubles import MemoryCredentials, MemoryNotifier
from engine.core.types import ConfigError, MemberRef, OAuthError, OrgId, ProviderAuth

KEY = SecretStr("k" * 44)
OTHER_KEY = SecretStr("j" * 44)
NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
MAX_AGE = 900

ORG_A = OrgId("org-a")
ORG_B = OrgId("org-b")
ADMIN = MemberRef("discord", "u1")

ACCESS = "ya29.access-token-value"
REFRESH = "1//refresh-token-value"
SECRET = "client-secret-value"
CODE = "4/authorization-code-value"


def state_for(org_id=ORG_A, provider="google", issued_at=NOW, member=ADMIN):
    return ConnectState(org_id=org_id, member=member, provider=provider, issued_at=issued_at)


# ---------------------------------------------------------------- the signed state


def test_a_signed_state_verifies_to_what_was_signed():
    token = sign(state_for(), KEY)
    assert verify(token, KEY, NOW, MAX_AGE) == state_for()


def test_the_same_state_signs_to_two_different_tokens():
    assert sign(state_for(), KEY) != sign(state_for(), KEY)


def test_the_token_does_not_show_the_key():
    assert KEY.get_secret_value() not in sign(state_for(), KEY)


@pytest.mark.parametrize(
    "token",
    ["", "nodot", "a.b.c", "....", "not-base64url!.zzzz"],
)
def test_a_token_that_is_not_a_signed_state_is_refused(token):
    with pytest.raises(OAuthError):
        verify(token, KEY, NOW, MAX_AGE)


def test_a_tampered_payload_is_refused():
    body, signature = sign(state_for(), KEY).split(".")
    swapped = sign(state_for(org_id=ORG_B), KEY).split(".")[0]
    with pytest.raises(OAuthError, match="signature"):
        verify(f"{swapped}.{signature}", KEY, NOW, MAX_AGE)
    with pytest.raises(OAuthError, match="signature"):
        verify(f"{body}.{sign(state_for(org_id=ORG_B), KEY).split('.')[1]}", KEY, NOW, MAX_AGE)


def test_a_state_signed_with_another_key_is_refused():
    with pytest.raises(OAuthError, match="signature"):
        verify(sign(state_for(), OTHER_KEY), KEY, NOW, MAX_AGE)


def test_an_expired_state_is_refused():
    token = sign(state_for(), KEY)
    assert verify(token, KEY, NOW + timedelta(seconds=MAX_AGE), MAX_AGE).org_id == ORG_A
    with pytest.raises(OAuthError, match="expired"):
        verify(token, KEY, NOW + timedelta(seconds=MAX_AGE + 1), MAX_AGE)


def test_a_state_issued_in_the_future_is_refused():
    token = sign(state_for(issued_at=NOW + timedelta(hours=1)), KEY)
    with pytest.raises(OAuthError, match="future"):
        verify(token, KEY, NOW, MAX_AGE)


def test_a_state_without_a_timezone_is_refused():
    with pytest.raises(OAuthError, match="timezone"):
        sign(state_for(issued_at=datetime(2026, 9, 15, 12, 0)), KEY)
    with pytest.raises(OAuthError, match="timezone"):
        verify(sign(state_for(), KEY), KEY, datetime(2026, 9, 15, 12, 0), MAX_AGE)


@pytest.mark.parametrize("key", [SecretStr(""), SecretStr("short"), SecretStr("k" * 31)])
def test_a_missing_or_weak_signing_key_says_so(key):
    with pytest.raises(ConfigError, match="signing key"):
        sign(state_for(), key)
    with pytest.raises(ConfigError, match="signing key"):
        verify(sign(state_for(), KEY), key, NOW, MAX_AGE)


def test_a_state_max_age_that_never_expires_is_refused():
    with pytest.raises(ConfigError, match="max age"):
        verify(sign(state_for(), KEY), KEY, NOW, 0)


def test_a_payload_of_another_version_is_refused():
    payload = {"v": 2, "org": ORG_A, "platform": "discord", "user": "u1"}
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    signature = base64.urlsafe_b64encode(_mac(body, KEY)).decode().rstrip("=")
    with pytest.raises(OAuthError, match="version"):
        verify(f"{body}.{signature}", KEY, NOW, MAX_AGE)


# ---------------------------------------------------------------- the callback route


def link(key=KEY, issued_at=None, **kwargs):
    """A connect link signed now, the way the gateway sends one."""
    return sign(state_for(issued_at=issued_at or datetime.now(UTC), **kwargs), key)


class RecordingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RecordingProvider(BaseProvider[RecordingSettings]):
    """A provider that records the code it was given and returns a credential for an org."""

    name: ClassVar[str] = "google"
    owns: ClassVar[tuple[str, ...]] = ()
    settings_model: ClassVar[type[BaseModel]] = RecordingSettings
    attach_to: ClassVar[OrgId | None] = None
    calls: ClassVar[list[tuple[OrgId, str]]] = []

    def authorize_url(self, state, scopes):
        return f"https://example.invalid/authorize?state={state}&scope={' '.join(scopes)}"

    async def exchange(self, org_id, code):
        type(self).calls.append((org_id, code))
        return ProviderAuth(
            org_id=self.attach_to or org_id,
            provider=self.name,
            access_token=SecretStr(ACCESS),
            scopes=("calendar",),
            expires_at=NOW + timedelta(hours=1),
            refresh_token=SecretStr(REFRESH),
        )

    async def refresh(self, auth):
        raise OAuthError("not used")


class FailingProvider(RecordingProvider):
    """A provider whose exchange fails the way a reused code does."""

    async def exchange(self, org_id, code):
        raise OAuthError(f"google rejected the token request: HTTP 400 invalid_grant {code}")


def build(provider_class=RecordingProvider, max_age=MAX_AGE):
    providers = Providers(
        {"google": ProviderSettings()},
        "https://zipy.example",
        classes={"google": provider_class},
    )
    credentials = MemoryCredentials()
    notifier = MemoryNotifier()
    routes = OAuthRoutes(
        providers,
        credentials,
        notifier,
        KEY,
        {"google": ["calendar"]},
        state_max_age_secs=max_age,
    )
    return routes, credentials, notifier


@pytest.fixture(autouse=True)
def _no_recorded_calls():
    RecordingProvider.calls = []
    RecordingProvider.attach_to = None
    yield
    RecordingProvider.calls = []
    RecordingProvider.attach_to = None


async def test_start_redirects_to_the_provider_with_the_state_and_scopes():
    routes, _, _ = build()
    token = link()
    response = await routes.start("google", token)
    assert response.status_code == 307
    assert token in response.headers["location"]
    assert "calendar" in response.headers["location"]
    assert response.headers["referrer-policy"] == "no-referrer"


async def test_start_refuses_a_state_that_does_not_verify():
    routes, _, _ = build()
    with pytest.raises(HTTPException) as raised:
        await routes.start("google", link(key=OTHER_KEY))
    assert raised.value.status_code == 400


async def test_the_callback_stores_the_credential_for_the_state_org_and_notifies():
    routes, credentials, notifier = build()
    response = await routes.callback("google", link(), code=CODE)
    assert response.status_code == 200
    stored = await credentials.get(ORG_A, "google")
    assert stored is not None
    assert stored.access_token.get_secret_value() == ACCESS
    assert notifier.sent == [(ORG_A, "google connected.")]


async def test_a_state_for_one_org_cannot_attach_a_credential_to_another():
    routes, credentials, notifier = build()
    RecordingProvider.attach_to = ORG_B
    response = await routes.callback("google", link(org_id=ORG_A), code=CODE)
    assert response.status_code == 400
    assert await credentials.get(ORG_A, "google") is None
    assert await credentials.get(ORG_B, "google") is None
    assert notifier.sent == []


async def test_a_state_for_another_org_cannot_be_forged_by_editing_the_token():
    routes, credentials, _ = build()
    body = link(org_id=ORG_B).split(".")[0]
    signature = link(org_id=ORG_A).split(".")[1]
    response = await routes.callback("google", f"{body}.{signature}", code=CODE)
    assert response.status_code == 400
    assert await credentials.get(ORG_B, "google") is None
    assert RecordingProvider.calls == []


async def test_a_state_signed_for_another_provider_is_refused():
    routes, credentials, _ = build()
    response = await routes.callback("google", link(provider="notion"), code=CODE)
    assert response.status_code == 400
    assert await credentials.get(ORG_A, "google") is None
    assert RecordingProvider.calls == []


async def test_an_expired_state_connects_nothing():
    routes, credentials, _ = build()
    old = link(issued_at=datetime.now(UTC) - timedelta(seconds=MAX_AGE + 60))
    response = await routes.callback("google", old, code=CODE)
    assert response.status_code == 400
    assert await credentials.get(ORG_A, "google") is None
    assert RecordingProvider.calls == []


async def test_an_unknown_provider_connects_nothing():
    routes, credentials, _ = build()
    response = await routes.callback("trello", link(provider="trello"), code=CODE)
    assert response.status_code == 400
    assert await credentials.get(ORG_A, "trello") is None


async def test_a_denied_grant_connects_nothing():
    routes, credentials, notifier = build()
    response = await routes.callback("google", link(), error="access_denied")
    assert response.status_code == 400
    assert await credentials.get(ORG_A, "google") is None
    assert notifier.sent == []


async def test_the_callback_never_shows_or_logs_the_code_or_the_tokens():
    routes, _, _ = build(FailingProvider)
    token = link()
    with structlog.testing.capture_logs() as logs:
        failed = await routes.callback("google", token, code=CODE)
        connected = await build()[0].callback("google", token, code=CODE)
    written = json.dumps(logs) + failed.body.decode() + connected.body.decode()
    for secret in (CODE, ACCESS, REFRESH, KEY.get_secret_value(), token):
        assert secret not in written


# ---------------------------------------------------------------- the provider plugins


class FakeResponse:
    def __init__(self, response):
        self._response = response
        self.sent = []

    async def post(self, url, **kwargs):
        self.sent.append((url, kwargs))
        return self._response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def fake_httpx(monkeypatch, module, response):
    client = FakeResponse(response)
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kwargs: client)
    return client


def google(**options):
    return GoogleProvider(
        GoogleSettings(client_id="id", client_secret=SecretStr(SECRET), **options),
        "https://zipy.example/auth/google/callback",
    )


def test_the_google_authorize_url_asks_for_offline_access():
    url = google().authorize_url("state-token", ["https://www.googleapis.com/auth/calendar"])
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "access_type=offline" in url
    assert "state=state-token" in url
    assert SECRET not in url


def test_google_without_scopes_is_refused():
    with pytest.raises(OAuthError, match="scope"):
        google().authorize_url("state-token", [])


async def test_google_exchange_returns_a_sealed_credential(monkeypatch):
    body = {"access_token": ACCESS, "refresh_token": REFRESH, "expires_in": 3599, "scope": "a b"}
    client = fake_httpx(monkeypatch, google_module, httpx.Response(200, json=body))
    auth = await google().exchange(ORG_A, CODE)
    assert auth.org_id == ORG_A
    assert auth.provider == "google"
    assert auth.scopes == ("a", "b")
    assert auth.expires_at is not None
    assert auth.access_token.get_secret_value() == ACCESS
    assert ACCESS not in repr(auth) and REFRESH not in repr(auth)
    assert client.sent[0][1]["data"]["code"] == CODE


async def test_google_exchange_without_a_refresh_token_is_refused(monkeypatch):
    body = {"access_token": ACCESS, "expires_in": 3599}
    fake_httpx(monkeypatch, google_module, httpx.Response(200, json=body))
    with pytest.raises(OAuthError, match="refresh token"):
        await google().exchange(ORG_A, CODE)


async def test_google_refresh_keeps_the_refresh_token_it_was_given(monkeypatch):
    fake_httpx(
        monkeypatch,
        google_module,
        httpx.Response(200, json={"access_token": "new-access", "expires_in": 60}),
    )
    auth = ProviderAuth(ORG_A, "google", SecretStr(ACCESS), ("a",), NOW, SecretStr(REFRESH))
    refreshed = await google().refresh(auth)
    assert refreshed.access_token.get_secret_value() == "new-access"
    assert refreshed.refresh_token is not None
    assert refreshed.refresh_token.get_secret_value() == REFRESH
    assert refreshed.scopes == ("a",)
    assert refreshed.org_id == ORG_A


async def test_a_credential_of_another_provider_is_not_refreshed_by_google():
    auth = ProviderAuth(ORG_A, "notion", SecretStr(ACCESS), (), None, SecretStr(REFRESH))
    with pytest.raises(OAuthError, match="notion"):
        await google().refresh(auth)


async def test_a_rejected_google_exchange_names_the_error_code_and_no_secret(monkeypatch):
    fake_httpx(
        monkeypatch,
        google_module,
        httpx.Response(400, json={"error": "invalid_grant", "access_token": ACCESS}),
    )
    with pytest.raises(OAuthError) as raised:
        await google().exchange(ORG_A, CODE)
    message = str(raised.value)
    assert "invalid_grant" in message
    for secret in (CODE, ACCESS, SECRET):
        assert secret not in message


async def test_a_google_client_without_a_secret_says_what_is_missing():
    provider = GoogleProvider(GoogleSettings(client_id="id"), "https://zipy.example/cb")
    with pytest.raises(OAuthError, match="client_secret"):
        await provider.exchange(ORG_A, CODE)


def test_the_notion_authorize_url_carries_the_state():
    provider = NotionProvider(
        NotionSettings(client_id="id", client_secret=SecretStr(SECRET)),
        "https://zipy.example/auth/notion/callback",
    )
    url = provider.authorize_url("state-token", [])
    assert url.startswith("https://api.notion.com/v1/oauth/authorize?")
    assert "state=state-token" in url
    assert SECRET not in url


async def test_a_notion_grant_cannot_be_refreshed():
    provider = NotionProvider(NotionSettings(client_id="id"), "https://zipy.example/cb")
    auth = ProviderAuth(ORG_A, "notion", SecretStr(ACCESS), (), None, None)
    with pytest.raises(OAuthError, match="do not expire"):
        await provider.refresh(auth)


def zoom(secret="zoom-webhook-secret"):
    return ZoomProvider(
        ZoomSettings(
            client_id="id", client_secret=SecretStr(SECRET), webhook_secret=SecretStr(secret)
        ),
        "https://zipy.example/auth/zoom/callback",
    )


def signed_webhook(body, secret="zoom-webhook-secret", timestamp="1789000000"):
    message = b"v0:" + timestamp.encode() + b":" + body
    digest = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return {"x-zm-request-timestamp": timestamp, "x-zm-signature": f"v0={digest}"}


async def test_a_zoom_webhook_with_a_valid_signature_is_accepted():
    body = json.dumps({"event": "recording.completed"}).encode()
    at = datetime.fromtimestamp(1789000000, UTC)
    assert zoom().verify_webhook(signed_webhook(body), body, at) == "recording.completed"


async def test_a_zoom_webhook_signed_with_another_secret_is_refused():
    body = json.dumps({"event": "recording.completed"}).encode()
    at = datetime.fromtimestamp(1789000000, UTC)
    with pytest.raises(OAuthError, match="signature"):
        zoom().verify_webhook(signed_webhook(body, secret="wrong"), body, at)


async def test_a_zoom_webhook_whose_body_changed_is_refused():
    body = json.dumps({"event": "recording.completed"}).encode()
    at = datetime.fromtimestamp(1789000000, UTC)
    with pytest.raises(OAuthError, match="signature"):
        zoom().verify_webhook(signed_webhook(body), body + b" ", at)


async def test_a_replayed_zoom_webhook_is_refused_once_it_is_stale():
    body = json.dumps({"event": "recording.completed"}).encode()
    at = datetime.fromtimestamp(1789000000 + 3600, UTC)
    with pytest.raises(OAuthError, match="window"):
        zoom().verify_webhook(signed_webhook(body), body, at)


async def test_a_zoom_webhook_without_a_signature_is_refused():
    body = json.dumps({"event": "recording.completed"}).encode()
    at = datetime.fromtimestamp(1789000000, UTC)
    with pytest.raises(OAuthError, match="no signature"):
        zoom().verify_webhook({}, body, at)


async def test_zoom_without_a_webhook_secret_says_what_is_missing():
    body = json.dumps({"event": "recording.completed"}).encode()
    at = datetime.fromtimestamp(1789000000, UTC)
    with pytest.raises(OAuthError, match="webhook_secret"):
        zoom(secret="").verify_webhook(signed_webhook(body), body, at)
