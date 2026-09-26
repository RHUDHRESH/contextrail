"""A test call is one deliberate provider POST after live-door and ownership checks."""

import json

import httpx
import pytest

from make_call import place_test_call

BASE = "https://voice.example.test/voice"
TO = "+919999999999"
FROM = "+918000000000"


def fake_transport(*, live=True, owned=True, error=False):
    posts = []

    def handle(request):
        if request.url == f"{BASE}/health":
            modes = {"vobiz_callbacks": "LIVE", "sarvam": "LIVE", "llm": "LIVE",
                     "llm_provider": "SARVAM", "engine": "configured"}
            if not live:
                modes["sarvam"] = "FIXTURE"
            return httpx.Response(200, json={"status": "ok", "base_url": BASE, "modes": modes})
        if request.url.path.endswith("/numbers"):
            items = [{"e164": FROM, "status": "active", "capabilities": {"voice": owned}}]
            return httpx.Response(200, json={"items": items})
        if request.method == "POST" and request.url.path.endswith("/Call/"):
            posts.append(json.loads(request.content))
            if error:
                raise httpx.ReadTimeout("unknown call outcome")
            return httpx.Response(202, json={"request_uuid": "provider-call-id"})
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    return httpx.MockTransport(handle), posts


def args(**overrides):
    return {"to": TO, "voice_base": BASE, "auth_id": "account", "auth_token": "secret"} | overrides


def test_preflight_only_queries_health_and_owned_number():
    transport, posts = fake_transport()
    result = place_test_call(**args(transport=transport))
    assert result.ready and not result.dialed and result.call_uuid is None
    assert result.from_last4 == "0000" and result.to_last4 == "9999"
    assert posts == []


def test_one_explicit_dial_uses_documented_contract():
    transport, posts = fake_transport()
    result = place_test_call(**args(transport=transport, dial=True))
    assert result.dialed and result.call_uuid == "provider-call-id"
    assert posts == [{"from": FROM, "to": TO, "answer_url": f"{BASE}/answer", "answer_method": "POST",
                      "hangup_url": f"{BASE}/hangup", "hangup_method": "POST"}]


@pytest.mark.parametrize("bad", ["http://voice.example.test/voice", "https://localhost/voice",
                                      "https://voice.example.test/voice?token=x"])
def test_public_https_is_required(bad):
    transport, posts = fake_transport()
    with pytest.raises(ValueError, match="public HTTPS"):
        place_test_call(**args(voice_base=bad, transport=transport, dial=True))
    assert posts == []


def test_fixture_or_unowned_caller_id_blocks_dial():
    for kwargs in ({"live": False}, {"owned": False}):
        transport, posts = fake_transport(**kwargs)
        with pytest.raises(ValueError):
            place_test_call(**args(transport=transport, dial=True))
        assert posts == []


def test_invalid_destination_blocks_dial():
    transport, posts = fake_transport()
    with pytest.raises(ValueError, match="E.164"):
        place_test_call(**args(to="9999999999", transport=transport, dial=True))
    assert posts == []


def test_unknown_post_outcome_is_not_retried():
    transport, posts = fake_transport(error=True)
    with pytest.raises(httpx.ReadTimeout):
        place_test_call(**args(transport=transport, dial=True))
    assert len(posts) == 1

