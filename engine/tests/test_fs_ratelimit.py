"""Token bucket for Freshservice's account-wide rate limit (T123, CLAUDE.md §12: default 80 calls/min).

Time is simulated: the bucket takes an injectable clock and sleep, so these tests never wait.
"""

import asyncio

import pytest
from _fs_mock import API_KEY, DOMAIN, FakeTenant, ok

from contextrail.connectors.freshservice import FreshserviceClient
from contextrail.connectors.ratelimit import TokenBucket
from contextrail.settings import Settings


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def bucket(t: FakeTime, rate: int = 80, burst: int | None = None) -> TokenBucket:
    return TokenBucket(rate, burst=burst, clock=t.clock, sleep=t.sleep)


def test_default_rate_is_80_per_minute():
    assert Settings(_env_file=None).fs_rate_limit_per_min == 80


async def test_a_burst_is_served_at_once_then_calls_are_paced():
    t = FakeTime()
    b = bucket(t)
    assert b.burst == 20
    for _ in range(20):
        await b.acquire()
    assert t.sleeps == []
    await b.acquire()
    assert t.sleeps == [pytest.approx(60 / 80)]


async def test_no_minute_ever_exceeds_the_smallest_plan_limit_and_the_long_run_rate_holds():
    t = FakeTime()
    b = bucket(t)
    stamps = []
    while t.now < 600:  # ten simulated minutes of callers that never stop
        await b.acquire()
        stamps.append(t.now)
    worst = max(sum(1 for s in stamps if start <= s < start + 60) for start in stamps)
    assert worst <= 100  # Freshservice plans allow 100-500/min, account-wide
    assert len(stamps) == pytest.approx(20 + 80 * 10, abs=2)


async def test_idle_time_refills_only_up_to_the_burst():
    t = FakeTime()
    b = bucket(t, rate=60, burst=5)
    for _ in range(5):
        await b.acquire()
    t.now += 3600
    for _ in range(5):
        await b.acquire()
    assert t.sleeps == []
    await b.acquire()
    assert t.sleeps == [pytest.approx(1.0)]


async def test_concurrent_callers_share_one_budget():
    t = FakeTime()
    b = bucket(t, rate=60, burst=2)
    await asyncio.gather(*(b.acquire() for _ in range(10)))
    assert t.now == pytest.approx(8.0)  # 2 free, then one per second


@pytest.mark.parametrize("rate,burst", [(0, None), (-5, None), (80, 0)])
def test_nonsense_limits_are_refused(rate, burst):
    with pytest.raises(ValueError):
        TokenBucket(rate, burst=burst)


async def test_the_client_takes_one_token_per_request():
    t = FakeTime()
    tenant = FakeTenant({("GET", "/api/v2/tickets/1"): ok({"ticket": {"id": 1}})})
    async with FreshserviceClient(DOMAIN, API_KEY, transport=tenant.transport,
                                  limiter=bucket(t, rate=60, burst=1)) as fs:
        for _ in range(3):
            await fs.get("tickets/1")
    assert len(tenant.requests) == 3
    assert t.now == pytest.approx(2.0)
