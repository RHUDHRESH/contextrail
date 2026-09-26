"""Router clients and the basic call path (T110 T1/T2 Anthropic clients, T111 T3 Bedrock). No network: fake clients,
or the real SDK clients over httpx2.MockTransport."""

import json

import anthropic
import httpx2
import pytest
from llm_fakes import FakeClient, api_error, config, message, settings

from contextrail.llm.router import (
    HAIKU_BEDROCK_ID,
    ModelNotAllowed,
    NoTierAvailable,
    Router,
    RouterConfig,
    build_clients,
)

USER = [{"role": "user", "content": "hi"}]


def _mocked(client, handler):
    """The same configured client (key, timeout, retries), talking to a local handler instead of the network."""
    return client.with_options(http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))


def _message_json(text: str = "Hello") -> dict:
    return message(text, input_tokens=12, output_tokens=3).model_dump(mode="json")


# --- T110: Tier 1 and Tier 2 direct clients ---------------------------------------------------------------

def test_one_direct_client_per_configured_key():
    s = settings(anthropic_key_a="test-key-a", anthropic_key_b="test-key-b")
    clients = build_clients(s, RouterConfig.from_settings(s))
    assert set(clients) == {"T1", "T2"}
    assert all(type(c) is anthropic.Anthropic for c in clients.values())
    assert (clients["T1"].api_key, clients["T2"].api_key) == ("test-key-a", "test-key-b")
    assert all(c.max_retries == 0 for c in clients.values())  # the router owns retries and failover (T113)
    assert all(c.timeout == 30 for c in clients.values())


def test_no_key_no_client():
    s = settings(anthropic_key_a="", anthropic_key_b="")
    assert build_clients(s, RouterConfig.from_settings(s)) == {}


async def test_first_tier_serves_haiku_and_is_reported():
    t1, t2 = FakeClient(message("Hello", input_tokens=12, output_tokens=3)), FakeClient()
    r = await Router(config(keys="AB"), {"T1": t1, "T2": t2}).call(
        system="You are terse.", messages=USER, max_tokens=50)
    assert (r.tier, r.model, r.text, r.input_tokens, r.output_tokens) == (
        "T1", "claude-haiku-4-5-20251001", "Hello", 12, 3)
    assert (r.replay, r.label) == (False, "llm:T1")
    assert t1.calls == [{"model": "claude-haiku-4-5-20251001", "system": "You are terse.", "messages": USER,
                         "max_tokens": 50}]
    assert t2.calls == []


async def test_optional_request_fields_are_sent_only_when_given():
    t1 = FakeClient(message(None, tool="t", tool_input={"x": 1}))
    tools = [{"name": "t", "input_schema": {"type": "object", "properties": {}}}]
    r = await Router(config(keys="A"), {"T1": t1}).call(
        system="s", messages=USER, max_tokens=10, tools=tools, tool_choice={"type": "tool", "name": "t"},
        thinking={"type": "disabled"}, temperature=0)
    sent = t1.calls[0]
    assert sent["model"] == "claude-haiku-4-5-20251001"
    assert (sent["tools"], sent["tool_choice"], sent["thinking"]) == (
        tools, {"type": "tool", "name": "t"}, {"type": "disabled"})
    assert sent["extra_body"] == {"temperature": 0}  # anthropic 1.8.0 has no typed temperature argument
    assert r.tool_input("t") == {"x": 1} and r.tool_input("other") is None


@pytest.mark.parametrize("other", ["claude-sonnet-5", "claude-opus-5", "sonnet"])
async def test_any_model_but_haiku_is_refused_before_any_client_is_called(other):
    t1 = FakeClient()
    with pytest.raises(ModelNotAllowed, match=other):
        await Router(config(keys="A"), {"T1": t1}).call(model=other, system="s", messages=USER, max_tokens=10)
    assert t1.calls == []


async def test_naming_haiku_explicitly_is_allowed():
    t1 = FakeClient(message("ok"))
    r = await Router(config(keys="A"), {"T1": t1}).call(model="claude-haiku-4-5-20251001", system="s",
                                                         messages=USER, max_tokens=10)
    assert r.text == "ok"


async def test_max_tokens_above_the_cap_is_refused():
    t1 = FakeClient()
    with pytest.raises(ValueError, match="max_tokens"):
        await Router(config(keys="A"), {"T1": t1}).call(system="s", messages=USER, max_tokens=801)
    assert t1.calls == []


async def test_no_enabled_tier_is_an_explicit_error():
    with pytest.raises(NoTierAvailable, match="claude-haiku-4-5-20251001"):
        await Router(config(keys=""), {}).call(system="s", messages=USER, max_tokens=10)


async def test_real_direct_client_request_shape():
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=_message_json("Hello"))

    s = settings(anthropic_key_a="test-key-a")
    cfg = RouterConfig.from_settings(s)
    t1 = _mocked(build_clients(s, cfg)["T1"], handler)
    r = await Router(cfg, {"T1": t1}).call(system="sys", messages=USER, max_tokens=40, temperature=0)
    assert r.text == "Hello" and r.tier == "T1"
    (req,) = seen
    assert req.url.host == "api.anthropic.com" and req.url.path == "/v1/messages"
    assert req.headers["x-api-key"] == "test-key-a"
    assert json.loads(req.content) == {"model": "claude-haiku-4-5-20251001", "system": "sys", "messages": USER,
                                       "max_tokens": 40, "temperature": 0}


def test_the_sdk_does_not_retry_behind_the_routers_back():
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(429, headers={"retry-after": "0"},
                               json={"type": "error", "error": {"type": "rate_limit_error", "message": "slow"}})

    s = settings(anthropic_key_a="test-key-a")
    cfg = RouterConfig.from_settings(s)
    with pytest.raises(anthropic.RateLimitError):
        _mocked(build_clients(s, cfg)["T1"], handler).messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=5, messages=USER)
    assert len(seen) == 1  # SDK default is 2 retries; the router decides instead


def test_fake_errors_are_the_sdks_own_classes():
    assert type(api_error(429)) is anthropic.RateLimitError and type(api_error(529)) is anthropic.OverloadedError
    assert type(api_error(503)) is anthropic.InternalServerError and type(api_error(400)) is anthropic.BadRequestError


# --- T111: Tier 3 Bedrock (Claude Haiku 4.5 global inference profile, ap-south-1) ---------------------------

@pytest.fixture
def fake_aws_env(monkeypatch):
    """SigV4 needs credentials to sign; these are obviously fake and never leave the process (MockTransport)."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-access-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret-key")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    for k in ("AWS_SESSION_TOKEN", "AWS_PROFILE", "AWS_BEARER_TOKEN_BEDROCK"):
        monkeypatch.delenv(k, raising=False)


def test_bedrock_client_is_anthropic_bedrock_in_ap_south_1():
    s = settings(bedrock_enabled=True)
    t3 = build_clients(s, RouterConfig.from_settings(s))["T3"]
    assert type(t3) is anthropic.AnthropicBedrock
    assert t3.aws_region == "ap-south-1" and str(t3.base_url) == "https://bedrock-runtime.ap-south-1.amazonaws.com"
    assert (t3.max_retries, t3.timeout) == (0, 30)


def test_bedrock_is_off_unless_enabled():
    s = settings(anthropic_key_a="test-key-a")
    assert "T3" not in build_clients(s, RouterConfig.from_settings(s))


async def test_bedrock_tier_sends_the_global_haiku_profile():
    t3 = FakeClient(message("ok"))
    r = await Router(config(keys="", bedrock=True), {"T3": t3}).call(system="s", messages=USER, max_tokens=10)
    assert (r.tier, r.model, r.label) == ("T3", HAIKU_BEDROCK_ID, "llm:T3")
    assert t3.calls[0]["model"] == "global.anthropic.claude-haiku-4-5-20251001-v1:0"


async def test_real_bedrock_client_signs_and_invokes_the_haiku_profile(fake_aws_env):
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=_message_json("Namaste"))

    s = settings(bedrock_enabled=True)
    cfg = RouterConfig.from_settings(s)
    t3 = _mocked(build_clients(s, cfg)["T3"], handler)
    r = await Router(cfg, {"T3": t3}).call(system="sys", messages=USER, max_tokens=40, temperature=0)
    assert (r.text, r.tier) == ("Namaste", "T3")
    (req,) = seen
    assert req.url.host == "bedrock-runtime.ap-south-1.amazonaws.com"
    assert req.url.path == "/model/global.anthropic.claude-haiku-4-5-20251001-v1:0/invoke"
    assert req.headers["authorization"].startswith("AWS4-HMAC-SHA256 Credential=test-access-key/")
    assert "/ap-south-1/bedrock/aws4_request" in req.headers["authorization"]
    body = json.loads(req.content)
    assert "model" not in body and body["anthropic_version"].startswith("bedrock-")
    assert (body["max_tokens"], body["temperature"]) == (40, 0)
