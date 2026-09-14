"""Admin command parsing and fitting replies to a platform's limit."""

import pytest

from engine.gateway.admin import AdminCommand, Verb, parse
from engine.gateway.render import split


def test_admin_commands_are_parsed_and_requests_are_not():
    assert parse("config calendar reminder 15") == AdminCommand(
        Verb.CONFIG, ("calendar", "reminder", "15")
    )
    assert parse("Status") == AdminCommand(Verb.STATUS, ())
    assert parse("when is the next exec board meeting?") is None


@pytest.mark.parametrize("limit", [2000, 3000])
def test_a_long_reply_is_split_at_newlines_within_the_limit(limit):
    text = "\n".join(f"line {i:04d}" for i in range(800))
    pieces = split(text, limit)
    assert all(len(p) <= limit for p in pieces)
    assert "\n".join(pieces) == text


def test_a_line_longer_than_the_limit_is_cut():
    assert split("x" * 4500, 2000) == ["x" * 2000, "x" * 2000, "x" * 500]


def test_the_local_protocol_accepts_only_known_ops():
    from engine.platforms.local.protocol import decode, encode

    assert decode('{"op": "ask", "text": "status"}') == {"op": "ask", "text": "status"}
    assert decode('{"op": "delete_everything"}') is None
    assert decode("not json") is None
    assert (
        encode("result", result={"answer": "hi"})
        == '{"type": "result", "result": {"answer": "hi"}}'
    )
