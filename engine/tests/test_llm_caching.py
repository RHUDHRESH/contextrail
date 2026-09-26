"""Prompt caching on the system prompt and policy text (T118, CLAUDE.md §11).

One explicit breakpoint on the last stable system block: it caches tools + system prompt + policy text. Explicit,
block-level `cache_control` (not the top-level request field) because the legacy Bedrock integration rejects the
top-level form. Note: Haiku 4.5 only caches prefixes of 4096+ tokens; shorter prefixes are sent uncached at no
premium, so the breakpoint is free until the policy text grows past that.
"""

import json

import httpx2
from llm_fakes import FakeClient, make_router, message, settings

from contextrail.llm.router import RouterConfig, build_clients

USER = [{"role": "user", "content": "hi"}]
EPHEMERAL = {"type": "ephemeral"}


async def test_system_prompt_is_a_cached_block():
    t1 = FakeClient(message("ok"))
    await make_router(_cfg(), {"T1": t1}).call(system="You are terse.", messages=USER, max_tokens=10)
    assert t1.calls[0]["system"] == [{"type": "text", "text": "You are terse.", "cache_control": EPHEMERAL}]


async def test_policy_text_follows_the_prompt_and_carries_the_one_breakpoint():
    t1 = FakeClient(message("ok"))
    await make_router(_cfg(), {"T1": t1}).call(system="Explain.", policy_text="POL-ACC-003: admin needs senior role.",
                                          messages=USER, max_tokens=10)
    assert t1.calls[0]["system"] == [
        {"type": "text", "text": "Explain."},
        {"type": "text", "text": "POL-ACC-003: admin needs senior role.", "cache_control": EPHEMERAL}]


async def test_cache_usage_is_reported():
    t1 = FakeClient(message("ok", input_tokens=40, cache_creation_input_tokens=4200, cache_read_input_tokens=0),
                    message("ok", input_tokens=40, cache_creation_input_tokens=0, cache_read_input_tokens=4200))
    router = make_router(_cfg(), {"T1": t1})
    first = await router.call(system="s", messages=USER, max_tokens=10)
    second = await router.call(system="s", messages=USER, max_tokens=10)
    assert (first.cache_write_tokens, first.cache_read_tokens) == (4200, 0)
    assert (second.cache_write_tokens, second.cache_read_tokens) == (0, 4200)


async def test_absent_cache_usage_reads_as_zero():
    r = await make_router(_cfg(), {"T1": FakeClient(message("ok"))}).call(system="s", messages=USER, max_tokens=10)
    assert (r.cache_write_tokens, r.cache_read_tokens) == (0, 0)


async def test_on_the_wire_the_breakpoint_is_block_level_not_top_level():
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=message("ok").model_dump(mode="json"))

    s = settings(anthropic_key_a="test-key-a")
    cfg = RouterConfig.from_settings(s)
    t1 = build_clients(s, cfg)["T1"].with_options(http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
    await make_router(cfg, {"T1": t1}).call(system="sys", policy_text="policy", messages=USER, max_tokens=10)
    body = json.loads(seen[0].content)
    assert "cache_control" not in body
    assert body["system"][-1] == {"type": "text", "text": "policy", "cache_control": EPHEMERAL}


def _cfg() -> RouterConfig:
    return RouterConfig.from_settings(settings(anthropic_key_a="test-key-a"))
