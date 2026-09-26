"""Per-tier circuit breaker (T114, CLAUDE.md §11): a tier that failed over is skipped for 180 s, then tried again."""

import pytest
from llm_fakes import FakeClient, Sleeps, api_error, config, message

from contextrail.llm.router import CircuitBreaker, LLMCallError, NoTierAvailable, Router

USER = [{"role": "user", "content": "hi"}]


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _router(clients: dict, clock: Clock, **cfg) -> Router:
    cfg = config(**{"keys": "AB", **cfg})
    return Router(cfg, clients, sleep=Sleeps(), breaker=CircuitBreaker(cfg.breaker_cooldown_s, clock=clock))


async def _call(router: Router):
    return await router.call(system="s", messages=USER, max_tokens=10)


async def test_a_failed_tier_is_skipped_within_180_s_and_retried_after():
    clock = Clock()
    t1 = FakeClient(api_error(529), message("T1 is back"))
    t2 = FakeClient(message("a"), message("b"))
    router = _router({"T1": t1, "T2": t2}, clock)

    assert (await _call(router)).tier == "T2"          # T1 529 -> fail over, T1's breaker opens
    clock.now += 179.9
    assert (await _call(router)).tier == "T2"          # still open: T1 not even tried
    assert len(t1.calls) == 1
    clock.now += 0.1                                   # 180 s after the failure
    r = await _call(router)
    assert (r.tier, r.text, len(t1.calls)) == ("T1", "T1 is back", 2)


async def test_a_retried_tier_that_fails_again_is_skipped_for_another_180_s():
    clock = Clock()
    t1 = FakeClient(api_error(500), api_error(500))
    t2 = FakeClient(message("a"), message("b"), message("c"))
    router = _router({"T1": t1, "T2": t2}, clock)
    await _call(router)
    clock.now += 180
    await _call(router)                                # T1 tried again, fails again, re-opened
    clock.now += 179
    await _call(router)
    assert len(t1.calls) == 2 and len(t2.calls) == 3


async def test_success_closes_the_breaker():
    clock = Clock()
    breaker = CircuitBreaker(180, clock=clock)
    breaker.trip("T1")
    assert breaker.is_open("T1")
    clock.now += 180
    assert not breaker.is_open("T1")
    breaker.trip("T1")
    breaker.reset("T1")
    assert not breaker.is_open("T1")


async def test_a_non_failover_error_does_not_open_the_breaker():
    clock = Clock()
    t1 = FakeClient(api_error(400, "bad request"), message("fine now"))
    router = _router({"T1": t1, "T2": FakeClient()}, clock)
    with pytest.raises(LLMCallError):
        await _call(router)
    assert (await _call(router)).tier == "T1"          # the request was bad, not the tier


async def test_a_429_that_succeeds_on_its_retry_does_not_open_the_breaker():
    clock = Clock()
    t1 = FakeClient(api_error(429, headers={"retry-after": "0"}), message("ok"), message("again"))
    router = _router({"T1": t1, "T2": FakeClient()}, clock)
    await _call(router)
    assert (await _call(router)).tier == "T1"


async def test_every_live_tier_open_is_no_tier_available_and_says_why():
    clock = Clock()
    router = _router({"T1": FakeClient(api_error(529)), "T2": FakeClient(api_error(529))}, clock)
    with pytest.raises(NoTierAvailable):
        await _call(router)
    clock.now += 10
    with pytest.raises(NoTierAvailable, match="breaker open"):
        await _call(router)


async def test_open_live_tiers_still_leave_replay(tmp_path):
    clock = Clock()
    recorder = Router(config(keys="A", replay="record", llm_replay_dir=str(tmp_path)),
                      {"T1": FakeClient(message("recorded"))})
    await _call(recorder)
    router = _router({"T1": FakeClient(api_error(503)), "T2": FakeClient(api_error(503))}, clock,
                     replay="replay", llm_replay_dir=str(tmp_path))
    assert (await _call(router)).replay is True
    clock.now += 5
    assert (await _call(router)).replay is True        # T1/T2 skipped without calls; T4 serves


async def test_default_breaker_uses_the_configured_180_s():
    router = Router(config(keys="A"), {})
    assert router.breaker.cooldown_s == 180
